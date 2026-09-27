"""Response-схема отложенного чека."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from checks_service.enums import CheckKind
from checks_service.formats.base import CheckPreview
from checks_service.main_api import PendingCheck


class PendingCheckResponse(BaseModel):
    """Отложенный чек: чем его узнать в списке и по какому id повторить.

    Сумма и время — из QR-строки, как на плашке до подтверждения. QR-строку
    наружу не отдаём: повтор идёт по id, и строка странице не нужна.
    """

    status: Literal["pending"] = "pending"
    id: int
    kind: CheckKind
    total: Decimal | None = None
    purchased_at: datetime | None = None

    @classmethod
    def of(cls, pending: PendingCheck, preview: CheckPreview) -> PendingCheckResponse:
        """Собирает ответ из строки api и сводки из QR."""
        return cls(
            id=pending.id,
            kind=pending.kind,
            total=preview.total,
            purchased_at=preview.purchased_at,
        )


class PendingChecksResponse(BaseModel):
    """Список отложенных чеков в порядке сканирования."""

    items: list[PendingCheckResponse]
