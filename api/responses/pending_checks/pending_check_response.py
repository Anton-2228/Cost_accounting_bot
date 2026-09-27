"""Response-схема отложенного чека."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import CheckKind


class PendingCheckResponse(BaseModel):
    """Отложенный чек: из чего запросить заново и как идут попытки."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    spreadsheet_id: int
    kind: CheckKind
    qr_raw: str
    external_key: str
    attempts: int
    next_attempt_at: datetime
    expired_at: datetime | None
    last_error: str | None
    created_at: datetime
