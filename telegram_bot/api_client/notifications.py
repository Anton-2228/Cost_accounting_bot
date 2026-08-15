"""Клиент сообщений о фоновой работе."""

from __future__ import annotations

from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import UserNotification


class NotificationsClient:
    """Чтение недоставленных сообщений и подтверждение отправки.

    Основной путь доставки — push от api в `POST /notify` бота. Эти два вызова
    нужны для второго, страховочного: когда пользователь обращается к боту,
    тот заодно дочитывает всё, что накопилось, пока он был недоступен.
    Подтверждение общее для обоих путей — иначе одно и то же сообщение
    отправлялось бы дважды.
    """

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_undelivered(self, spreadsheet_id: int) -> list[UserNotification]:
        """Сообщения документа, которые бот ещё не показал."""
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/notifications")
        return [UserNotification.model_validate(item) for item in items]

    async def mark_delivered(self, spreadsheet_id: int, notification_id: int) -> None:
        """Подтверждает, что сообщение показано. Повтор безопасен."""
        await self._http.post_empty(
            f"/spreadsheets/{spreadsheet_id}/notifications/{notification_id}/delivered"
        )
