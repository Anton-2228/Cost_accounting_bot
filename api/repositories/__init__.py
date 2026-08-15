"""Репозитории: доступ к данным, DTO на входе и на выходе.

Ни один репозиторий не коммитит — транзакцией управляет сервисный слой.
"""

from __future__ import annotations

from api.repositories.base import BaseRepository
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.check_queue_repository import CheckQueueRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.sheet_mapping_repository import SheetMappingRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_access_repository import SpreadsheetAccessRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.transfer_repository import TransferRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.repositories.user_repository import UserRepository

__all__ = [
    "BaseRepository",
    "CashedRecordRepository",
    "CategoryRepository",
    "CheckQueueRepository",
    "PeriodRepository",
    "RecordRepository",
    "SheetMappingRepository",
    "SheetSyncTaskRepository",
    "SourceRepository",
    "SpreadsheetAccessRepository",
    "SpreadsheetRepository",
    "TransferRepository",
    "UserNotificationRepository",
    "UserRepository",
]
