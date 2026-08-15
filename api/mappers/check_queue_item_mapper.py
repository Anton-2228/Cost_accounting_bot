"""Маппер чека в очереди."""

from __future__ import annotations

from api.domain.check_queue_item import CheckQueueItem
from api.mappers.base import BaseMapper
from api.orm.check_queue_item import CheckQueueItemORM


class CheckQueueItemMapper(BaseMapper[CheckQueueItemORM, CheckQueueItem]):
    """Элемент очереди чеков."""

    def to_domain(self, orm: CheckQueueItemORM) -> CheckQueueItem:
        """Преобразует ORM-объект в доменную модель."""
        return CheckQueueItem(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            check_text=orm.check_text,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: CheckQueueItem) -> CheckQueueItemORM:
        """Создаёт ORM-объект из доменной модели."""
        return CheckQueueItemORM(
            spreadsheet_id=domain.spreadsheet_id,
            check_text=domain.check_text,
        )
