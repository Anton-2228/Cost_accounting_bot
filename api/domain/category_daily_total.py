"""Производная величина: дневной итог по категории."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from api.core.types import SignedMoneyDecimal


class CategoryDailyTotal(BaseModel):
    """Сумма операций одной категории за один день периода.

    Строка агрегата для листа статистики. Сумма считается в `Decimal` и
    приходит без округления: прежний код сворачивал её через `int()`, из-за
    чего копейки терялись, а расходы (отрицательные) систематически
    занижались — `int(-1234.56)` даёт `-1234`.
    """

    category_id: int
    day: date
    total: SignedMoneyDecimal
