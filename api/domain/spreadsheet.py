"""Доменная модель учётной таблицы."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.core import constants
from api.core.types import ResetDay


class Spreadsheet(BaseModel):
    """Учётная таблица пользователя.

    `google_spreadsheet_id` пуст, пока `google_sheets_service` не создал
    документ: api в Google не ходит.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    user_id: int
    google_spreadsheet_id: str | None = None
    title: str
    reset_day: ResetDay
    timezone: str = constants.DEFAULT_TIMEZONE
    created_at: datetime | None = None
    updated_at: datetime | None = None
