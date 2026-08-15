"""Доменная модель перевода между счетами."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from api.core.types import PositiveMoneyDecimal


class Transfer(BaseModel):
    """Перемещение денег между двумя счетами одного документа.

    Ни доходом, ни расходом не является и в статистику не попадает. Сумма
    строго положительна, направление задают `from_source_id` и `to_source_id`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    period_id: int
    from_source_id: int
    to_source_id: int
    amount: PositiveMoneyDecimal
    added_at: date
    notes: str = ""
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
