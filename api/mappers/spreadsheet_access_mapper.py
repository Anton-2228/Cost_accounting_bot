"""Маппер доступа к Google-документу."""

from __future__ import annotations

from api.domain.spreadsheet_access import SpreadsheetAccess
from api.mappers.base import BaseMapper
from api.orm.spreadsheet_access import SpreadsheetAccessORM


class SpreadsheetAccessMapper(BaseMapper[SpreadsheetAccessORM, SpreadsheetAccess]):
    """Выданный (или ожидающий выдачи) доступ к документу."""

    def to_domain(self, orm: SpreadsheetAccessORM) -> SpreadsheetAccess:
        """Преобразует ORM-объект в доменную модель."""
        return SpreadsheetAccess(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            email=orm.email,
            role=orm.role,
            granted_at=orm.granted_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: SpreadsheetAccess) -> SpreadsheetAccessORM:
        """Создаёт ORM-объект из доменной модели."""
        return SpreadsheetAccessORM(
            spreadsheet_id=domain.spreadsheet_id,
            email=domain.email,
            role=domain.role,
            granted_at=domain.granted_at,
        )
