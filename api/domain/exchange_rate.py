"""Доменная модель курса одной валюты к другой на конкретный день."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from api.enums import Currency


class ExchangeRate(BaseModel):
    """Сколько единиц `quote` стоила одна единица `base` в день `rate_date`.

    Курс — глобальный факт, а не свойство документа: он одинаков для всех
    пользователей, поэтому `spreadsheet_id` здесь нет и кэш общий.

    Курса валюты к себе самой не бывает: он всегда единица, хранить её значило
    бы держать в таблице четыре бессмысленные строки на каждый день и рисковать
    тем, что однажды в них окажется не единица. В SQL она подставляется через
    `CASE`, см. :mod:`api.repositories.source_repository`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    base_currency: Currency
    quote_currency: Currency
    rate_date: date
    rate: Decimal
    created_at: datetime | None = None
    updated_at: datetime | None = None


#: Что именно требуется знать, чтобы посчитать агрегат: из какой валюты, в
#: какую и на какой день. Множество таких троек собирается запросом к тем же
#: таблицам, по которым потом пойдёт агрегация, — см.
#: :meth:`api.services.exchange_rate_service.ExchangeRateService.ensure`.
type RateRequirement = tuple[Currency, Currency, date]
