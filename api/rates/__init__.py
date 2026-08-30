"""Получение курсов валют у внешнего источника.

Устроено как `checks_service.formats`: протокол отдельно, реализация отдельно.
Смена источника — один новый класс, вызывающий код не трогается.
"""

from __future__ import annotations

from api.rates.base import RateProvider, RateUnavailableError
from api.rates.currency_api import CurrencyApiProvider, parse_rates

__all__ = [
    "CurrencyApiProvider",
    "RateProvider",
    "RateUnavailableError",
    "parse_rates",
]
