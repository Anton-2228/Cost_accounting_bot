"""Маппер учётного периода."""

from __future__ import annotations

from api.domain.period import Period
from api.mappers.base import BaseMapper
from api.orm.period import PeriodORM


class PeriodMapper(BaseMapper[PeriodORM, Period]):
    """Учётный период."""

    def to_domain(self, orm: PeriodORM) -> Period:
        """Преобразует ORM-объект в доменную модель."""
        return Period(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            start_date=orm.start_date,
            end_date=orm.end_date,
            status=orm.status,
            closed_at=orm.closed_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: Period) -> PeriodORM:
        """Создаёт ORM-объект из доменной модели."""
        return PeriodORM(
            spreadsheet_id=domain.spreadsheet_id,
            start_date=domain.start_date,
            end_date=domain.end_date,
            status=domain.status,
            closed_at=domain.closed_at,
        )
