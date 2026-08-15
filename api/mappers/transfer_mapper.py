"""Маппер перевода между счетами."""

from __future__ import annotations

from api.domain.transfer import Transfer
from api.mappers.base import BaseMapper
from api.orm.transfer import TransferORM


class TransferMapper(BaseMapper[TransferORM, Transfer]):
    """Перевод между счетами."""

    def to_domain(self, orm: TransferORM) -> Transfer:
        """Преобразует ORM-объект в доменную модель."""
        return Transfer(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            period_id=orm.period_id,
            from_source_id=orm.from_source_id,
            to_source_id=orm.to_source_id,
            amount=orm.amount,
            added_at=orm.added_at,
            notes=orm.notes,
            deleted_at=orm.deleted_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: Transfer) -> TransferORM:
        """Создаёт ORM-объект из доменной модели."""
        return TransferORM(
            spreadsheet_id=domain.spreadsheet_id,
            period_id=domain.period_id,
            from_source_id=domain.from_source_id,
            to_source_id=domain.to_source_id,
            amount=domain.amount,
            added_at=domain.added_at,
            notes=domain.notes,
            deleted_at=domain.deleted_at,
        )
