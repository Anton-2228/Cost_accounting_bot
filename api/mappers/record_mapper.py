"""Маппер операции."""

from __future__ import annotations

from api.domain.record import Record
from api.mappers.base import BaseMapper
from api.orm.record import RecordORM


class RecordMapper(BaseMapper[RecordORM, Record]):
    """Операция реестра."""

    def to_domain(self, orm: RecordORM) -> Record:
        """Преобразует ORM-объект в доменную модель."""
        return Record(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            period_id=orm.period_id,
            category_id=orm.category_id,
            source_id=orm.source_id,
            amount=orm.amount,
            added_at=orm.added_at,
            notes=orm.notes,
            product_name=orm.product_name,
            product_type=orm.product_type,
            check_id=orm.check_id,
            deleted_at=orm.deleted_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: Record) -> RecordORM:
        """Создаёт ORM-объект из доменной модели."""
        return RecordORM(
            spreadsheet_id=domain.spreadsheet_id,
            period_id=domain.period_id,
            category_id=domain.category_id,
            source_id=domain.source_id,
            amount=domain.amount,
            added_at=domain.added_at,
            notes=domain.notes,
            product_name=domain.product_name,
            product_type=domain.product_type,
            check_id=domain.check_id,
            deleted_at=domain.deleted_at,
        )
