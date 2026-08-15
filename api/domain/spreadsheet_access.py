"""Доменная модель доступа к Google-документу."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import AccessRole


class SpreadsheetAccess(BaseModel):
    """Почта с доступом к документу.

    `granted_at is None` означает «доступ ещё предстоит выдать в Google».
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    email: str
    role: AccessRole = AccessRole.WRITER
    granted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
