"""ORM-модели.

Импорт этого пакета регистрирует все таблицы в `Base.metadata` — на него
опираются `create_all` в тестах и autogenerate в Alembic.
"""

from __future__ import annotations

from api.orm.cashed_record import CashedRecordORM
from api.orm.category import CategoryORM
from api.orm.category_association import CategoryAssociationORM
from api.orm.category_product_type import CategoryProductTypeORM
from api.orm.check import CheckORM
from api.orm.llm_usage import LlmUsageORM
from api.orm.period import PeriodORM
from api.orm.record import RecordORM
from api.orm.sheet_mapping import SheetMappingORM
from api.orm.sheet_sync_task import SheetSyncTaskORM
from api.orm.source import SourceORM
from api.orm.source_association import SourceAssociationORM
from api.orm.spreadsheet import SpreadsheetORM
from api.orm.spreadsheet_access import SpreadsheetAccessORM
from api.orm.transfer import TransferORM
from api.orm.user import UserORM
from api.orm.user_notification import UserNotificationORM

__all__ = [
    "CashedRecordORM",
    "CategoryAssociationORM",
    "CategoryORM",
    "CategoryProductTypeORM",
    "CheckORM",
    "LlmUsageORM",
    "PeriodORM",
    "RecordORM",
    "SheetMappingORM",
    "SheetSyncTaskORM",
    "SourceAssociationORM",
    "SourceORM",
    "SpreadsheetAccessORM",
    "SpreadsheetORM",
    "TransferORM",
    "UserNotificationORM",
    "UserORM",
]
