"""Дочитка уведомлений, пропущенных, пока бот был недоступен."""

from __future__ import annotations

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiError
from telegram_bot.logging import get_logger

logger = get_logger(__name__)


class NotificationCatchUp:
    """Досылает накопившиеся сообщения при обращении пользователя.

    Страховка, а не основной путь: обычно уведомление приходит push-ом от api
    в `POST /notify`. Но если бот лежал в момент события, а цикл рассылки в api
    почему-то не догнал очередь, пользователь иначе никогда не узнает, что
    правки в листе не применились, — текст разбора существует только здесь.

    Подтверждение идёт тем же эндпоинтом, что и у push: одно и то же сообщение
    не должно уйти дважды.

    Ошибки не выпускаются наружу: дочитка сопровождает команду пользователя и
    не имеет права её уронить. Не получилось — сообщение осталось в очереди и
    приедет в следующий раз.
    """

    def __init__(self, api: ApiGateway, aiogram_wrapper: AiogramWrapper) -> None:
        self._api = api
        self._aiogram = aiogram_wrapper

    async def deliver(self, spreadsheet_id: int, chat_id: int) -> int:
        """Отправляет всё недоставленное. Возвращает число отправленных."""
        try:
            pending = await self._api.notifications.list_undelivered(spreadsheet_id)
        except ApiError as error:
            logger.warning("Не удалось прочитать уведомления: %s", error)
            return 0

        delivered = 0
        for notification in pending:
            try:
                await self._aiogram.send_message(chat_id, notification.text)
                await self._api.notifications.mark_delivered(spreadsheet_id, notification.id)
            except ApiError as error:
                logger.warning("Не удалось подтвердить уведомление: %s", error)
                break
            except Exception:
                logger.exception("Не удалось отправить уведомление %s", notification.id)
                break
            delivered += 1
        return delivered
