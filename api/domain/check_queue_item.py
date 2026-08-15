"""Доменная модель чека в очереди на разбор."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckQueueItem(BaseModel):
    """Сырой текст чека, ожидающий обработки."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    check_text: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
