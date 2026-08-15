"""Response-схема счёта."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.core.types import MoneyDecimal
from api.enums import EntityStatus


class SourceResponse(BaseModel):
    """Счёт в ответе.

    Текущего баланса здесь нет: он не хранится, а считается. См.
    :class:`api.responses.sources.source_balance_response.SourceBalanceResponse`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: EntityStatus
    title: str
    associations: list[str]
    start_balance: MoneyDecimal
