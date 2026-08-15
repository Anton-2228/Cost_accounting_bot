"""Response-схема перевода."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from api.core.types import PositiveMoneyDecimal


class TransferResponse(BaseModel):
    """Перевод в ответе.

    Сумма строго положительна: направление задают счета, а не знак. В доходы и
    расходы перевод не попадает — деньги не появились и не исчезли.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    period_id: int
    from_source_id: int
    to_source_id: int
    amount: PositiveMoneyDecimal
    added_at: date
    notes: str
