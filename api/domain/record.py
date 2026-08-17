"""Доменная модель операции."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from api.core.types import SignedMoneyDecimal


class Record(BaseModel):
    """Одна операция реестра.

    `amount` знаковая: расход отрицателен, доход положителен. Знак ставит
    сервис по виду категории — пользователь передаёт сумму без знака, и
    отрицательное значение от него не может «перевернуть» операцию, как это
    происходило раньше.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    period_id: int
    category_id: int
    source_id: int
    amount: SignedMoneyDecimal
    added_at: date
    notes: str = ""
    product_name: str | None = None
    product_type: str | None = None
    check_id: int | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
