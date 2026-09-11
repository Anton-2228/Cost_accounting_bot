"""HTTP-эндпоинт, через который api толкает боту уведомления."""

from __future__ import annotations

from typing import Any

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from fastapi import FastAPI, Response, status
from pydantic import BaseModel, ConfigDict, Field

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client.models import NotificationKind
from telegram_bot.commands.menu import MenuCommand
from telegram_bot.formatting.notification_formatter import NotificationFormatter
from telegram_bot.i18n import Language, current_language, language_scope
from telegram_bot.logging import get_logger

logger = get_logger(__name__)

#: Ограничение Telegram на длину сообщения.
_MAX_TEXT_LENGTH = 4096

#: Отказы Telegram, которые повтор не лечит.
#:
#: `TelegramForbiddenError` — бот заблокирован или удалён из чата.
#: `TelegramNotFound` и `TelegramBadRequest` — запрос неисполним как таковой:
#: «chat not found» (пользователь ни разу не писал боту, и начать диалог первым
#: бот не может), неверная разметка, слишком длинный текст. Ответ Telegram на
#: тот же запрос не изменится, сколько его ни повторяй.
_PERMANENT_ERRORS = (TelegramForbiddenError, TelegramNotFound, TelegramBadRequest)


class NotifyPayload(BaseModel):
    """Тело запроса `POST /notify`."""

    model_config = ConfigDict(extra="forbid")

    notification_id: int
    telegram_id: int
    #: Язык получателя — тот, что лежит в `users.language`. Строкой, а не
    #: перечислением: незнакомый язык не должен ронять доставку, бот тогда
    #: просто говорит на языке по умолчанию.
    language: str
    kind: str
    code: str
    params: dict[str, Any] = Field(default_factory=dict)


class NotifyServer:
    """FastAPI-приложение с одним содержательным эндпоинтом.

    Поднимается рядом с polling-ом. Аутентификации нет: порт не публикуется
    наружу и доступен только внутри docker-сети.

    Договор с api описан кодом ответа:

    * **204** — «дальше не повторять». Либо сообщение отправлено, либо
      отправить его невозможно в принципе (см. `_PERMANENT_ERRORS`), и сотая
      попытка получит тот же отказ.
    * **503** — временная неудача: Telegram попросил подождать, ответил 5xx или
      оборвалась сеть. Api оставит сообщение в очереди и повторит следующим
      проходом.

    Граница между этими случаями существенна с обеих сторон. Отвечать 204 на
    всё подряд нельзя: тогда `delivered_at` означал бы «api попробовал», а не
    «пользователь увидел», и сообщение о неудачном разборе листа исчезло бы
    навсегда. Но и отвечать 503 на неисправимый отказ нельзя: сообщение
    остаётся в очереди вечно, и каждые несколько секунд в журнал уходит один и
    тот же стектрейс — а вместе с ним и все остальные уведомления этого
    пользователя, которых он тоже никогда не получит.
    """

    def __init__(self, aiogram_wrapper: AiogramWrapper, menu: MenuCommand) -> None:
        self._aiogram = aiogram_wrapper
        self._menu = menu

    def build_app(self) -> FastAPI:
        """Собирает приложение с зарегистрированными маршрутами."""
        app = FastAPI(title="Telegram bot notify server", version="0.1.0")
        app.add_api_route("/notify", self._notify, methods=["POST"])
        app.add_api_route("/health", self._health, methods=["GET"])
        return app

    async def _notify(self, payload: NotifyPayload) -> Response:
        """Отправляет сообщение пользователю на его языке.

        Язык едет в самом пакете: api знает его тем же запросом, которым нашёл
        получателя, и спрашивать его отсюда ещё раз было бы лишним кругом. Меню
        по `TABLE_READY` рисуется в той же области — на том же языке.
        """
        language = Language.from_code(payload.language) or current_language()
        with language_scope(language):
            return await self._deliver(payload)

    async def _deliver(self, payload: NotifyPayload) -> Response:
        """Собирает текст и отправляет его; код ответа — по договору выше.

        Сборка текста не бросает (см. `NotificationFormatter`): исключение здесь
        стало бы ответом 503, и api повторял бы то же уведомление вечно.
        """
        text = NotificationFormatter.render(payload.code, payload.params)[:_MAX_TEXT_LENGTH]
        try:
            await self._aiogram.send_message(payload.telegram_id, text)
        except _PERMANENT_ERRORS as error:
            # Стектрейс здесь не нужен: причина видна из сообщения Telegram, а
            # случай штатный. Уведомление снимается с очереди — иначе оно будет
            # повторяться до конца времён.
            logger.warning(
                "Уведомление %s не доставить пользователю %s (%s) — снимаем с очереди",
                payload.notification_id,
                payload.telegram_id,
                error,
            )
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except TelegramRetryAfter as error:
            logger.warning("Telegram просит подождать %s с", error.retry_after)
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception:
            logger.exception("Не удалось отправить уведомление %s", payload.notification_id)
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

        await self._show_menu_if_ready(payload)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def _show_menu_if_ready(self, payload: NotifyPayload) -> None:
        """Дорисовывает меню, когда приехало «таблица готова».

        До этого момента меню не показывалось ни разу: мастер заканчивается
        обещанием, а все кнопки экрана работают с документом, которого ещё нет.
        Это и есть момент, когда обещание исполнено, — и узнаёт о нём бот
        отсюда, а не от пользователя.

        Отказ отрисовки глушится логом и **не меняет код ответа**. Текст уже
        доставлен: ответив 503, бот попросил бы api прислать его второй раз, и
        пользователь получил бы «таблица готова» дважды из-за не нарисованного
        экрана.

        `kind` сравнивается строкой, а не разбирается в `StrEnum`: незнакомый
        вид уведомления не должен ронять его доставку — печатать бот умеет
        любой.
        """
        if payload.kind != NotificationKind.TABLE_READY.value:
            return
        try:
            await self._menu.show(chat_id=payload.telegram_id)
        except Exception:
            logger.exception("Меню после готовности таблицы не нарисовано")

    async def _health(self) -> dict[str, str]:
        """Проверка живости для healthcheck контейнера."""
        return {"status": "ok"}
