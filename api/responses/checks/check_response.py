"""Response-схема сохранённого чека."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.enums import CheckKind


class CheckResponse(BaseModel):
    """Сохранённый чек. Разбирает его отдельный шаг, api пока только хранит."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: CheckKind
    qr_raw: str
    external_key: str
    raw_payload: dict[str, Any]
    fetched_at: datetime
    created_at: datetime
