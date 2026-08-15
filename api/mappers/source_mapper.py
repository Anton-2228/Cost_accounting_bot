"""Маппер источника денег."""

from __future__ import annotations

from api.domain.source import Source
from api.mappers.base import BaseMapper
from api.orm.source import SourceORM
from api.orm.source_association import SourceAssociationORM


class SourceMapper(BaseMapper[SourceORM, Source]):
    """Счёт вместе с дочерними псевдонимами.

    Текущий баланс не переносится ни в одну сторону: его в строке нет, он
    считается агрегатом.
    """

    def to_domain(self, orm: SourceORM) -> Source:
        """Преобразует ORM-объект в доменную модель."""
        return Source(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            status=orm.status,
            title=orm.title,
            associations=[row.alias for row in orm.association_rows],
            start_balance=orm.start_balance,
            deleted_at=orm.deleted_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: Source) -> SourceORM:
        """Создаёт ORM-объект вместе с дочерними строками псевдонимов."""
        return SourceORM(
            spreadsheet_id=domain.spreadsheet_id,
            status=domain.status,
            title=domain.title,
            start_balance=domain.start_balance,
            deleted_at=domain.deleted_at,
            association_rows=self.association_rows(domain),
        )

    @staticmethod
    def association_rows(domain: Source) -> list[SourceAssociationORM]:
        """Строит дочерние строки псевдонимов (без `source_id` — его проставит ORM)."""
        return [
            SourceAssociationORM(spreadsheet_id=domain.spreadsheet_id, alias=alias)
            for alias in domain.associations
        ]
