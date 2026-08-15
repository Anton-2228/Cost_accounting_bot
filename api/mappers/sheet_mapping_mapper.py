"""Маппер соответствия «адресат → лист документа»."""

from __future__ import annotations

from api.domain.sheet_mapping import SheetMapping
from api.mappers.base import BaseMapper
from api.orm.sheet_mapping import SheetMappingORM


class SheetMappingMapper(BaseMapper[SheetMappingORM, SheetMapping]):
    """Соответствие адресата перерисовки листу документа."""

    def to_domain(self, orm: SheetMappingORM) -> SheetMapping:
        """Преобразует ORM-объект в доменную модель."""
        return SheetMapping(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            target=orm.target,
            period_id=orm.period_id,
            google_sheet_id=orm.google_sheet_id,
            title=orm.title,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: SheetMapping) -> SheetMappingORM:
        """Создаёт ORM-объект из доменной модели."""
        return SheetMappingORM(
            spreadsheet_id=domain.spreadsheet_id,
            target=domain.target,
            period_id=domain.period_id,
            google_sheet_id=domain.google_sheet_id,
            title=domain.title,
        )
