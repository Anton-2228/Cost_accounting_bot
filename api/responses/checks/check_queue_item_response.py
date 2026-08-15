"""Response-схема чека в очереди."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckQueueItemResponse(BaseModel):
    """Сырой чек, ожидающий разбора. Разбирает его бот, api только хранит."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    check_text: str
    created_at: datetime
