"""Request-схема «отложи чек»."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.enums import CheckKind


class AddPendingCheckRequest(BaseModel):
    """Тело запроса «внешний сервис чек пока не отдал — спросим позже»."""

    model_config = ConfigDict(extra="forbid")

    kind: CheckKind
    qr_raw: str = Field(min_length=1)
    external_key: str = Field(min_length=1)
    #: Машинный код отказа (`receipt_not_ready`, …).
    error: str = Field(min_length=1)
