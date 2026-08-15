"""Response-схема посчитанного баланса счёта."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.core.types import SignedMoneyDecimal


class SourceBalanceResponse(BaseModel):
    """Счёт вместе с балансом. Баланс знаковый: счёт может уйти в минус."""

    model_config = ConfigDict(from_attributes=True)

    source_id: int
    title: str
    start_balance: SignedMoneyDecimal
    balance: SignedMoneyDecimal
