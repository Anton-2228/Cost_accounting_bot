"""Маппер учётной таблицы."""

from __future__ import annotations

from api.domain.spreadsheet import Spreadsheet
from api.mappers.base import BaseMapper
from api.orm.spreadsheet import SpreadsheetORM


class SpreadsheetMapper(BaseMapper[SpreadsheetORM, Spreadsheet]):
    """Учётная таблица пользователя."""

    def to_domain(self, orm: SpreadsheetORM) -> Spreadsheet:
        """Преобразует ORM-объект в доменную модель."""
        return Spreadsheet(
            id=orm.id,
            user_id=orm.user_id,
            google_spreadsheet_id=orm.google_spreadsheet_id,
            title=orm.title,
            reset_day=orm.reset_day,
            timezone=orm.timezone,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: Spreadsheet) -> SpreadsheetORM:
        """Создаёт ORM-объект из доменной модели."""
        return SpreadsheetORM(
            user_id=domain.user_id,
            google_spreadsheet_id=domain.google_spreadsheet_id,
            title=domain.title,
            reset_day=domain.reset_day,
            timezone=domain.timezone,
        )
