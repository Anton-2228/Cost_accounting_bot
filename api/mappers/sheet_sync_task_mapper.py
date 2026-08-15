"""Маппер задачи на перерисовку листа."""

from __future__ import annotations

from api.domain.sheet_sync_task import SheetSyncTask
from api.mappers.base import BaseMapper
from api.orm.sheet_sync_task import SheetSyncTaskORM


class SheetSyncTaskMapper(BaseMapper[SheetSyncTaskORM, SheetSyncTask]):
    """Задача очереди перерисовки."""

    def to_domain(self, orm: SheetSyncTaskORM) -> SheetSyncTask:
        """Преобразует ORM-объект в доменную модель."""
        return SheetSyncTask(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            kind=orm.kind,
            target=orm.target,
            period_id=orm.period_id,
            requested_at=orm.requested_at,
            claimed_at=orm.claimed_at,
            attempts=orm.attempts,
            next_attempt_at=orm.next_attempt_at,
            last_error=orm.last_error,
        )

    def to_orm(self, domain: SheetSyncTask) -> SheetSyncTaskORM:
        """Создаёт ORM-объект из доменной модели.

        `requested_at` и `next_attempt_at` не выставляются: их проставляет БД
        своим `now()`, и это принципиально — метки времени очереди должны идти
        по часам одного источника, а не по часам процесса.
        """
        return SheetSyncTaskORM(
            spreadsheet_id=domain.spreadsheet_id,
            kind=domain.kind,
            target=domain.target,
            period_id=domain.period_id,
        )
