"""Доменная модель сообщения пользователю."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.enums import NotificationKind


class UserNotification(BaseModel):
    """Отложенное сообщение о результате фоновой работы.

    Текста в нём нет — только код и данные для подстановки (см.
    :class:`api.domain.user_message.UserMessage`): фразу на языке пользователя
    собирает бот. `kind` — класс события, `code` — какая именно фраза.

    `delivered_at` заполняется, когда бот подтвердил отправку. Строка при этом
    остаётся: история уведомлений полезна при разборе жалоб «мне ничего не
    пришло».
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    kind: NotificationKind
    code: str
    params: dict[str, Any] = {}
    delivered_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
