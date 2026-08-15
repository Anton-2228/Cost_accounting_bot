"""Фабрики репозиториев как зависимости FastAPI.

Каждый репозиторий создаётся на сессии, выданной `get_session`. За счёт
кэширования зависимостей одна и та же `AsyncSession` переиспользуется в пределах
запроса — общая для всех репозиториев и для сервиса, который их получил.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.session import get_session
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


def get_user_repository(session: AsyncSession = Depends(get_session)) -> UserRepository:
    """Репозиторий пользователей."""
    return UserRepository(session)


def get_spreadsheet_repository(
    session: AsyncSession = Depends(get_session),
) -> SpreadsheetRepository:
    """Репозиторий учётных таблиц."""
    return SpreadsheetRepository(session)


def get_spreadsheet_access_repository(
    session: AsyncSession = Depends(get_session),
) -> SpreadsheetAccessRepository:
    """Репозиторий доступов к документу."""
    return SpreadsheetAccessRepository(session)


def get_period_repository(session: AsyncSession = Depends(get_session)) -> PeriodRepository:
    """Репозиторий учётных периодов."""
    return PeriodRepository(session)


def get_category_repository(session: AsyncSession = Depends(get_session)) -> CategoryRepository:
    """Репозиторий категорий."""
    return CategoryRepository(session)


def get_source_repository(session: AsyncSession = Depends(get_session)) -> SourceRepository:
    """Репозиторий счетов."""
    return SourceRepository(session)


def get_record_repository(session: AsyncSession = Depends(get_session)) -> RecordRepository:
    """Репозиторий операций."""
    return RecordRepository(session)


def get_transfer_repository(session: AsyncSession = Depends(get_session)) -> TransferRepository:
    """Репозиторий переводов."""
    return TransferRepository(session)


def get_cashed_record_repository(
    session: AsyncSession = Depends(get_session),
) -> CashedRecordRepository:
    """Репозиторий кэша «товар → тип»."""
    return CashedRecordRepository(session)


def get_check_queue_repository(
    session: AsyncSession = Depends(get_session),
) -> CheckQueueRepository:
    """Репозиторий очереди чеков."""
    return CheckQueueRepository(session)


def get_sheet_sync_task_repository(
    session: AsyncSession = Depends(get_session),
) -> SheetSyncTaskRepository:
    """Репозиторий очереди перерисовки листов."""
    return SheetSyncTaskRepository(session)


def get_sheet_mapping_repository(
    session: AsyncSession = Depends(get_session),
) -> SheetMappingRepository:
    """Репозиторий соответствий «адресат → лист»."""
    return SheetMappingRepository(session)


def get_user_notification_repository(
    session: AsyncSession = Depends(get_session),
) -> UserNotificationRepository:
    """Репозиторий уведомлений пользователю."""
    return UserNotificationRepository(session)
