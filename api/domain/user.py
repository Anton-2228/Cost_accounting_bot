"""Доменная модель пользователя Telegram."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    """Пользователь бота."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    telegram_id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
