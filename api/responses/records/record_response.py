"""Response-схема операции."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from api.core.types import SignedMoneyDecimal
from api.enums import Currency


class RecordResponse(BaseModel):
    """Операция в ответе.

    `amount` знаковая: расход отрицателен, доход положителен, и выражена она
    в `currency` — валюте операции, не обязательно совпадающей с валютой
    счёта. Приведённой к счёту суммы здесь нет: она зависит от курса и
    считается агрегатом остатка.

    `check_id` выдаётся наружу как есть. Прежде он сворачивался в булев
    `from_check` — листу операций хватало галочки в колонке `Check`. Теперь в
    этой колонке стоит номер чека, а сам чек лежит строкой на листе-архиве:
    идентификатор и есть ссылка между ними, и сворачивать его больше не во что.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    period_id: int
    category_id: int
    source_id: int
    amount: SignedMoneyDecimal
    currency: Currency
    added_at: date
    notes: str
    product_name: str | None
    product_type: str | None
    check_id: int | None = None
