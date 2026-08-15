"""Общие типы колонок: деньги и нативные enum-типы PostgreSQL.

Каждый enum объявлен **один раз** и привязан к `Base.metadata`. Это важно: если
создавать `Enum(...)` заново в каждой ORM-модели, `create_all` попытается
выполнить `CREATE TYPE` столько раз, сколько таблиц использует тип. Привязка к
метаданным делает создание и удаление типа частью жизненного цикла схемы.

SQLAlchemy записывает в нативный enum **имя** члена, а не значение. Во всех
перечислениях :mod:`api.enums` имя и значение совпадают, поэтому неоднозначности
«в БД EXPENSE, в коде expense» не возникает.
"""

from __future__ import annotations

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Numeric

from api.core import constants
from api.db.base import Base
from api.enums import (
    AccessRole,
    CategoryKind,
    CheckKind,
    EntityStatus,
    NotificationKind,
    PeriodStatus,
    SheetTarget,
    SyncTaskKind,
)

#: Денежная колонка. Точность согласована с :mod:`api.core.constants`.
MONEY = Numeric(constants.MONEY_MAX_DIGITS, constants.MONEY_DECIMAL_PLACES)

ENTITY_STATUS = SAEnum(
    EntityStatus,
    name="entity_status",
    metadata=Base.metadata,
)

CATEGORY_KIND = SAEnum(
    CategoryKind,
    name="category_kind",
    metadata=Base.metadata,
)

CHECK_KIND = SAEnum(
    CheckKind,
    name="check_kind",
    metadata=Base.metadata,
)

PERIOD_STATUS = SAEnum(
    PeriodStatus,
    name="period_status",
    metadata=Base.metadata,
)

SHEET_TARGET = SAEnum(
    SheetTarget,
    name="sheet_target",
    metadata=Base.metadata,
)

ACCESS_ROLE = SAEnum(
    AccessRole,
    name="access_role",
    metadata=Base.metadata,
)

SYNC_TASK_KIND = SAEnum(
    SyncTaskKind,
    name="sync_task_kind",
    metadata=Base.metadata,
)

NOTIFICATION_KIND = SAEnum(
    NotificationKind,
    name="notification_kind",
    metadata=Base.metadata,
)
