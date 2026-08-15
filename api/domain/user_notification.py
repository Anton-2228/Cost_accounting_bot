"""Доменная модель сообщения пользователю."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import NotificationKind


class UserNotification(BaseModel):
    """Готовое к отправке сообщение о результате фоновой работы.

    `delivered_at` заполняется, когда бот подтвердил отправку. Строка при этом
    остаётся: история уведомлений полезна при разборе жалоб «мне ничего не
    пришло».
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    kind: NotificationKind
    text: str
    delivered_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
