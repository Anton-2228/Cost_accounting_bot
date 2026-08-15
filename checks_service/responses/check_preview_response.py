"""Response-схема плашки распознанного чека."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from checks_service.enums import CheckKind
from checks_service.services.check_intake import Preview


class CheckPreviewResponse(BaseModel):
    """Что показать пользователю до подтверждения.

    Сумма и время необязательные: они собраны из самой QR-строки, а формат
    может их и не нести. Плашка тогда покажет только вид чека и название
    таблицы, куда он ляжет.
    """

    kind: CheckKind
    spreadsheet_title: str
    total: Decimal | None = None
    purchased_at: datetime | None = None

    @classmethod
    def of(cls, preview: Preview) -> CheckPreviewResponse:
        """Собирает ответ из результата распознавания."""
        return cls(
            kind=preview.parsed.kind,
            spreadsheet_title=preview.spreadsheet_title,
            total=preview.parsed.preview.total,
            purchased_at=preview.parsed.preview.purchased_at,
        )
