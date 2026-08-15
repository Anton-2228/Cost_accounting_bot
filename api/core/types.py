"""Переиспользуемые типы для pydantic-моделей.

Точность денежных типов берётся из :mod:`api.core.constants` — там же, где
задана точность колонок `NUMERIC` в БД, поэтому ограничение не расползается по
моделям.

Денежных типов ровно два, и путать их нельзя:

* :data:`MoneyDecimal` — величина без знака (сумма перевода, начальный баланс).
* :data:`SignedMoneyDecimal` — знаковая величина (`records.amount`: расход
  отрицательный, доход положительный). Навесить на неё `MoneyDecimal` значит
  завалить валидацией каждый расход ещё до похода в БД.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import Field

from api.core import constants

#: Неотрицательная денежная сумма.
MoneyDecimal = Annotated[
    Decimal,
    Field(
        max_digits=constants.MONEY_MAX_DIGITS,
        decimal_places=constants.MONEY_DECIMAL_PLACES,
        ge=0,
    ),
]

#: Строго положительная денежная сумма (сумма перевода).
PositiveMoneyDecimal = Annotated[
    Decimal,
    Field(
        max_digits=constants.MONEY_MAX_DIGITS,
        decimal_places=constants.MONEY_DECIMAL_PLACES,
        gt=0,
    ),
]

#: Знаковая денежная сумма: расход < 0, доход > 0.
SignedMoneyDecimal = Annotated[
    Decimal,
    Field(
        max_digits=constants.MONEY_MAX_DIGITS,
        decimal_places=constants.MONEY_DECIMAL_PLACES,
    ),
]

#: День сброса учётного периода.
ResetDay = Annotated[
    int,
    Field(ge=constants.MIN_RESET_DAY, le=constants.MAX_RESET_DAY),
]
