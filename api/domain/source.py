"""Доменная модель источника денег."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from api.core.text import normalize_terms
from api.core.types import MoneyDecimal
from api.enums import Currency, EntityStatus


class Source(BaseModel):
    """Счёт.

    Текущего баланса здесь нет: он производная величина, см.
    :class:`api.domain.source_balance.SourceBalance`.

    `currency` — валюта, в которой ведётся счёт. В ней задан `start_balance` и в
    ней же выражен вычисленный остаток; операция в другой валюте приводится к
    этой по курсу на день операции.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    status: EntityStatus = EntityStatus.ACTIVE
    title: str
    currency: Currency
    associations: list[str] = []
    start_balance: MoneyDecimal = Decimal("0.00")
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("associations", mode="after")
    @classmethod
    def _normalize(cls, value: list[str]) -> list[str]:
        """Приводит псевдонимы к нижнему регистру, убирает дубли и сортирует."""
        return normalize_terms(value)
