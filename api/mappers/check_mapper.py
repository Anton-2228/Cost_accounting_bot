"""Маппер сохранённого чека."""

from __future__ import annotations

from api.domain.check import Check
from api.mappers.base import BaseMapper
from api.orm.check import CheckORM


class CheckMapper(BaseMapper[CheckORM, Check]):
    """Чек: сырьё и вид формата."""

    def to_domain(self, orm: CheckORM) -> Check:
        """Преобразует ORM-объект в доменную модель."""
        return Check(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            kind=orm.kind,
            qr_raw=orm.qr_raw,
            external_key=orm.external_key,
            raw_payload=orm.raw_payload,
            fetched_at=orm.fetched_at,
            processed_at=orm.processed_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: Check) -> CheckORM:
        """Создаёт ORM-объект из доменной модели."""
        return CheckORM(
            spreadsheet_id=domain.spreadsheet_id,
            kind=domain.kind,
            qr_raw=domain.qr_raw,
            external_key=domain.external_key,
            raw_payload=domain.raw_payload,
            fetched_at=domain.fetched_at,
            processed_at=domain.processed_at,
        )
