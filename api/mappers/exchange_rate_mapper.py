"""Маппер курса валют."""

from __future__ import annotations

from api.domain.exchange_rate import ExchangeRate
from api.mappers.base import BaseMapper
from api.orm.exchange_rate import ExchangeRateORM


class ExchangeRateMapper(BaseMapper[ExchangeRateORM, ExchangeRate]):
    """Строка кэша курсов."""

    def to_domain(self, orm: ExchangeRateORM) -> ExchangeRate:
        """Преобразует ORM-объект в доменную модель."""
        return ExchangeRate(
            id=orm.id,
            base_currency=orm.base_currency,
            quote_currency=orm.quote_currency,
            rate_date=orm.rate_date,
            rate=orm.rate,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: ExchangeRate) -> ExchangeRateORM:
        """Создаёт ORM-объект из доменной модели."""
        return ExchangeRateORM(
            base_currency=domain.base_currency,
            quote_currency=domain.quote_currency,
            rate_date=domain.rate_date,
            rate=domain.rate,
        )
