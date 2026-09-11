"""Доменная модель пользователя Telegram."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import Language


class User(BaseModel):
    """Пользователь бота.

    Умолчание языка повторяет умолчание колонки: пользователь, заведённый
    вместе с таблицей без выбора языка, получает тот же язык, что получил бы
    от самой БД.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    telegram_id: int
    language: Language = Language.EN
    created_at: datetime | None = None
    updated_at: datetime | None = None
