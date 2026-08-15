"""Доменная модель уведомления, готового к отправке в бота."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.enums import NotificationKind


class PendingNotification(BaseModel):
    """Недоставленное сообщение вместе с адресом получателя.

    Отдельная модель рядом с :class:`api.domain.user_notification.UserNotification`
    нужна из-за адресации. Сама строка уведомления знает только документ, а
    отправлять надо в чат Telegram, и `telegram_id` лежит через две таблицы
    (`user_notifications → spreadsheets → users`). Класть его в `UserNotification`
    нельзя: там он был бы `None` во всех остальных сценариях, и каждый
    вызывающий был бы обязан помнить, заполнено поле или нет.

    Модель не имеет обратного отображения в ORM: это результат выборки с
    join'ом, а не сущность.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    spreadsheet_id: int
    telegram_id: int
    kind: NotificationKind
    text: str
