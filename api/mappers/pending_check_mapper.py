"""Маппер отложенного чека."""

from __future__ import annotations

from api.domain.pending_check import PendingCheck
from api.mappers.base import BaseMapper
from api.orm.pending_check import PendingCheckORM


class PendingCheckMapper(BaseMapper[PendingCheckORM, PendingCheck]):
    """Отложенный чек: QR-строка и состояние попыток."""

    def to_domain(self, orm: PendingCheckORM) -> PendingCheck:
        """Преобразует ORM-объект в доменную модель."""
        return PendingCheck(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            kind=orm.kind,
            qr_raw=orm.qr_raw,
            external_key=orm.external_key,
            attempts=orm.attempts,
            window_started_at=orm.window_started_at,
            next_attempt_at=orm.next_attempt_at,
            claimed_at=orm.claimed_at,
            expired_at=orm.expired_at,
            last_error=orm.last_error,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: PendingCheck) -> PendingCheckORM:
        """Создаёт ORM-объект из доменной модели.

        `window_started_at` без значения отдаётся серверному умолчанию `now()`.
        """
        orm = PendingCheckORM(
            spreadsheet_id=domain.spreadsheet_id,
            kind=domain.kind,
            qr_raw=domain.qr_raw,
            external_key=domain.external_key,
            attempts=domain.attempts,
            next_attempt_at=domain.next_attempt_at,
            claimed_at=domain.claimed_at,
            expired_at=domain.expired_at,
            last_error=domain.last_error,
        )
        if domain.window_started_at is not None:
            orm.window_started_at = domain.window_started_at
        return orm
