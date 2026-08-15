"""Маппер выученного соответствия «товар → тип»."""

from __future__ import annotations

from api.domain.cashed_record import CashedRecord
from api.mappers.base import BaseMapper
from api.orm.cashed_record import CashedRecordORM


class CashedRecordMapper(BaseMapper[CashedRecordORM, CashedRecord]):
    """Запись кэша типов товаров."""

    def to_domain(self, orm: CashedRecordORM) -> CashedRecord:
        """Преобразует ORM-объект в доменную модель."""
        return CashedRecord(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            product_name=orm.product_name,
            product_type=orm.product_type,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: CashedRecord) -> CashedRecordORM:
        """Создаёт ORM-объект из доменной модели."""
        return CashedRecordORM(
            spreadsheet_id=domain.spreadsheet_id,
            product_name=domain.product_name,
            product_type=domain.product_type,
        )
