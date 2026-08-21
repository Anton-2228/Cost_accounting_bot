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

    `deleted_at` — метка отвязывания (`/table_unlink`). Заполненная означает,
    что документ больше не работа для бота и не текущий документ пользователя,
    но записи учёта и траты на модель по нему остаются.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    user_id: int
    google_spreadsheet_id: str | None = None
    title: str
    reset_day: ResetDay
    timezone: str = constants.DEFAULT_TIMEZONE
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
