"""Адресат перерисовки в Google-документе."""

from __future__ import annotations

from enum import StrEnum


class SheetTarget(StrEnum):
    """Какой лист устарел и подлежит перерисовке.

    `STRUCTURE` — не лист, а сам документ: создание таблицы, выдача доступов,
    добавление листов нового периода.

    `OPERATIONS` и `STATISTICS` привязаны к конкретному периоду, остальные —
    нет. Это различие закреплено ограничением в БД, см.
    :class:`api.orm.sheet_sync_task.SheetSyncTaskORM`.
    """

    STRUCTURE = "STRUCTURE"
    CATEGORIES = "CATEGORIES"
    BILLS = "BILLS"
    OPERATIONS = "OPERATIONS"
    STATISTICS = "STATISTICS"

    @property
    def requires_period(self) -> bool:
        """Нужен ли этому адресату период."""
        return self in _PERIOD_TARGETS


_PERIOD_TARGETS = frozenset({SheetTarget.OPERATIONS, SheetTarget.STATISTICS})
