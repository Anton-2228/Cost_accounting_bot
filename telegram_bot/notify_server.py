"""HTTP-эндпоинт, через который api толкает боту уведомления."""

from __future__ import annotations

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from fastapi import FastAPI, Response, status
from pydantic import BaseModel, ConfigDict, Field

from telegram_bot.aiogram_wrapper import AiogramWrapper
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
    kind: str
    text: str = Field(min_length=1, max_length=_MAX_TEXT_LENGTH)


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

    def __init__(self, aiogram_wrapper: AiogramWrapper) -> None:
        self._aiogram = aiogram_wrapper

    def build_app(self) -> FastAPI:
        """Собирает приложение с зарегистрированными маршрутами."""
        app = FastAPI(title="Telegram bot notify server", version="0.1.0")
        app.add_api_route("/notify", self._notify, methods=["POST"])
        app.add_api_route("/health", self._health, methods=["GET"])
        return app

    async def _notify(self, payload: NotifyPayload) -> Response:
        """Отправляет сообщение пользователю."""
        try:
            await self._aiogram.send_message(payload.telegram_id, payload.text)
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

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def _health(self) -> dict[str, str]:
        """Проверка живости для healthcheck контейнера."""
        return {"status": "ok"}
