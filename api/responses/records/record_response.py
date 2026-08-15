"""Response-схема операции."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, computed_field

from api.core.types import SignedMoneyDecimal


class RecordResponse(BaseModel):
    """Операция в ответе.

    `amount` знаковая: расход отрицателен, доход положителен.

    Сырой JSON чека наружу не выдаётся, а превращается в признак `from_check`:
    он лежит в каждой позиции чека целиком, и список операций за месяц иначе
    вырос бы до нескольких мегабайт — при том, что колонке `Check` на листе
    нужна одна отметка. Понадобится сам чек — это будет отдельный эндпоинт по
    одной операции, а не поле в списке.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    period_id: int
    category_id: int
    source_id: int
    amount: SignedMoneyDecimal
    added_at: date
    notes: str
    product_name: str | None
    product_type: str | None
    check_json: str | None = Field(default=None, exclude=True)

    # mypy не поддерживает декораторы над @property; сочетание
    # computed_field + property — рекомендованный pydantic способ отдать
    # производное поле, поэтому подавляем именно эту проверку.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def from_check(self) -> bool:
        """Операция распознана из чека."""
        return self.check_json is not None
