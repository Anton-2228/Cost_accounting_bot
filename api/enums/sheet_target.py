"""Адресат перерисовки в Google-документе."""

from __future__ import annotations

from enum import StrEnum


class SheetTarget(StrEnum):
    """Какой лист устарел и подлежит перерисовке.

    `STRUCTURE` — не лист, а сам документ: создание таблицы, выдача доступов,
    добавление листов нового периода.

    `OPERATIONS`, `STATISTICS` и `CHECKS` привязаны к конкретному периоду,
    остальные — нет. Это различие закреплено ограничением в БД, см.
    :class:`api.orm.sheet_sync_task.SheetSyncTaskORM`.

    `CHECKS` — архив разобранных чеков месяца: строка на чек, в ней его
    расшифровка целиком. Месяц у чека берётся от его операций, поэтому адресат
    периодный, как и реестр.
    """

    STRUCTURE = "STRUCTURE"
    CATEGORIES = "CATEGORIES"
    BILLS = "BILLS"
    OPERATIONS = "OPERATIONS"
    STATISTICS = "STATISTICS"
    CHECKS = "CHECKS"

    @property
    def requires_period(self) -> bool:
        """Нужен ли этому адресату период."""
        return self in _PERIOD_TARGETS


_PERIOD_TARGETS = frozenset(
    {SheetTarget.OPERATIONS, SheetTarget.STATISTICS, SheetTarget.CHECKS}
)
