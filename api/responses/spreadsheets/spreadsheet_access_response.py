"""Response-схема доступа к документу."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import AccessRole


class SpreadsheetAccessResponse(BaseModel):
    """Доступ в ответе. `granted_at is None` — доступ ещё предстоит выдать."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: AccessRole
    granted_at: datetime | None
