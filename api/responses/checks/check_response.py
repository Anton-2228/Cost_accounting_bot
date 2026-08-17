"""Response-схема сохранённого чека."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.enums import CheckKind


class CheckResponse(BaseModel):
    """Сохранённый чек: сырьё и отметка о разборе.

    `raw_payload` отдаётся целиком: позиции из него достаёт бот, и решать за
    него, какие поля формата понадобятся, api не может — форматов будет больше
    одного.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: CheckKind
    qr_raw: str
    external_key: str
    raw_payload: dict[str, Any]
    fetched_at: datetime
    processed_at: datetime | None
    created_at: datetime
