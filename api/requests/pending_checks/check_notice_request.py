"""Request-схема сводки чека для уведомления."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from api.domain.check_summary import CheckNotice


class CheckNoticeRequest(BaseModel):
    """Сумма и время покупки из QR-строки — чтобы назвать чек в уведомлении."""

    model_config = ConfigDict(extra="forbid")

    total: Decimal
    purchased_at: datetime

    def to_domain(self) -> CheckNotice:
        """Доменная сводка."""
        return CheckNotice(total=self.total, purchased_at=self.purchased_at)
