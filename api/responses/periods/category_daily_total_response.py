"""Response-схема дневного итога по категории."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from api.core.types import SignedMoneyDecimal


class CategoryDailyTotalResponse(BaseModel):
    """Сумма одной категории за один день периода.

    Из этих строк складывается лист статистики. Сумма знаковая и не округлена:
    прежний код сворачивал её через `int()` и систематически занижал расходы.
    """

    model_config = ConfigDict(from_attributes=True)

    category_id: int
    day: date
    total: SignedMoneyDecimal
