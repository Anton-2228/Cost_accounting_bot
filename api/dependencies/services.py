"""Фабрики сервисов как зависимости FastAPI.

Сервис получает ту же сессию, что и его репозитории (FastAPI кэширует
`get_session` в пределах запроса), поэтому единственный коммит внутри сервиса
завершает общую транзакцию: и сама запись, и постановка задач в очередь листов
попадают в БД целиком или никак.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.session import get_session
from api.dependencies.repositories import (
    get_cashed_record_repository,
    get_category_repository,
    get_check_repository,
    get_llm_usage_repository,
    get_period_repository,
    get_record_repository,
    get_sheet_mapping_repository,
    get_sheet_sync_task_repository,
    get_source_repository,
    get_spreadsheet_access_repository,
    get_spreadsheet_repository,
    get_transfer_repository,
    get_user_notification_repository,
    get_user_repository,
)
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.check_repository import CheckRepository
from api.repositories.llm_usage_repository import LlmUsageRepository
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
from api.services.category_import_service import CategoryImportService
from api.services.check_service import CheckService
from api.services.llm_usage_service import LlmUsageService
from api.services.notification_service import NotificationService
from api.services.period_service import PeriodService
from api.services.record_service import RecordService
from api.services.sheet_mapping_service import SheetMappingService
from api.services.sheet_sync_task_service import SheetSyncTaskService
from api.services.source_import_service import SourceImportService
from api.services.spreadsheet_service import SpreadsheetService
from api.services.transfer_service import TransferService


def get_spreadsheet_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    users: UserRepository = Depends(get_user_repository),
    periods: PeriodRepository = Depends(get_period_repository),
    categories: CategoryRepository = Depends(get_category_repository),
    sources: SourceRepository = Depends(get_source_repository),
    accesses: SpreadsheetAccessRepository = Depends(get_spreadsheet_access_repository),
    tasks: SheetSyncTaskRepository = Depends(get_sheet_sync_task_repository),
    notifications: UserNotificationRepository = Depends(get_user_notification_repository),
) -> SpreadsheetService:
    """Сервис жизненного цикла документа."""
    return SpreadsheetService(
        session,
        spreadsheets,
        users=users,
        periods=periods,
        categories=categories,
        sources=sources,
        accesses=accesses,
        tasks=tasks,
        notifications=notifications,
    )


def get_record_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    periods: PeriodRepository = Depends(get_period_repository),
    categories: CategoryRepository = Depends(get_category_repository),
    sources: SourceRepository = Depends(get_source_repository),
    records: RecordRepository = Depends(get_record_repository),
    cashed_records: CashedRecordRepository = Depends(get_cashed_record_repository),
    checks: CheckRepository = Depends(get_check_repository),
    tasks: SheetSyncTaskRepository = Depends(get_sheet_sync_task_repository),
) -> RecordService:
    """Сервис операций реестра."""
    return RecordService(
        session,
        spreadsheets,
        periods=periods,
        categories=categories,
        sources=sources,
        records=records,
        cashed_records=cashed_records,
        checks=checks,
        tasks=tasks,
    )


def get_transfer_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    periods: PeriodRepository = Depends(get_period_repository),
    sources: SourceRepository = Depends(get_source_repository),
    transfers: TransferRepository = Depends(get_transfer_repository),
    tasks: SheetSyncTaskRepository = Depends(get_sheet_sync_task_repository),
) -> TransferService:
    """Сервис переводов между счетами."""
    return TransferService(
        session,
        spreadsheets,
        periods=periods,
        sources=sources,
        transfers=transfers,
        tasks=tasks,
    )


def get_check_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    periods: PeriodRepository = Depends(get_period_repository),
    categories: CategoryRepository = Depends(get_category_repository),
    sources: SourceRepository = Depends(get_source_repository),
    records: RecordRepository = Depends(get_record_repository),
    cashed_records: CashedRecordRepository = Depends(get_cashed_record_repository),
    checks: CheckRepository = Depends(get_check_repository),
    tasks: SheetSyncTaskRepository = Depends(get_sheet_sync_task_repository),
) -> CheckService:
    """Сервис чеков: сохранение сырья, кэш типов и запись разобранного чека."""
    return CheckService(
        session,
        spreadsheets,
        periods=periods,
        categories=categories,
        sources=sources,
        records=records,
        cashed_records=cashed_records,
        checks=checks,
        tasks=tasks,
    )


def get_llm_usage_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    usages: LlmUsageRepository = Depends(get_llm_usage_repository),
) -> LlmUsageService:
    """Сервис учёта обращений к модели."""
    return LlmUsageService(session, spreadsheets, usages=usages)


def get_period_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    periods: PeriodRepository = Depends(get_period_repository),
    records: RecordRepository = Depends(get_record_repository),
) -> PeriodService:
    """Сервис чтения периодов и дневных итогов."""
    return PeriodService(session, spreadsheets, periods=periods, records=records)


def get_category_import_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    categories: CategoryRepository = Depends(get_category_repository),
    periods: PeriodRepository = Depends(get_period_repository),
    cashed_records: CashedRecordRepository = Depends(get_cashed_record_repository),
    tasks: SheetSyncTaskRepository = Depends(get_sheet_sync_task_repository),
    notifications: UserNotificationRepository = Depends(get_user_notification_repository),
) -> CategoryImportService:
    """Сервис вчитывания листа `Categories`."""
    return CategoryImportService(
        session,
        spreadsheets,
        categories=categories,
        periods=periods,
        cashed_records=cashed_records,
        tasks=tasks,
        notifications=notifications,
    )


def get_source_import_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    sources: SourceRepository = Depends(get_source_repository),
    periods: PeriodRepository = Depends(get_period_repository),
    tasks: SheetSyncTaskRepository = Depends(get_sheet_sync_task_repository),
    notifications: UserNotificationRepository = Depends(get_user_notification_repository),
) -> SourceImportService:
    """Сервис вчитывания листа `Bills`."""
    return SourceImportService(
        session,
        spreadsheets,
        sources=sources,
        periods=periods,
        tasks=tasks,
        notifications=notifications,
    )


def get_sheet_sync_task_service(
    session: AsyncSession = Depends(get_session),
    tasks: SheetSyncTaskRepository = Depends(get_sheet_sync_task_repository),
    notifications: UserNotificationRepository = Depends(get_user_notification_repository),
) -> SheetSyncTaskService:
    """Сервис очереди перерисовки листов (служебный, для gsheets)."""
    return SheetSyncTaskService(session, tasks, notifications)


def get_sheet_mapping_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    mappings: SheetMappingRepository = Depends(get_sheet_mapping_repository),
    periods: PeriodRepository = Depends(get_period_repository),
) -> SheetMappingService:
    """Сервис соответствий «адресат → лист» (служебный, для gsheets)."""
    return SheetMappingService(session, spreadsheets, mappings=mappings, periods=periods)


def get_notification_service(
    session: AsyncSession = Depends(get_session),
    spreadsheets: SpreadsheetRepository = Depends(get_spreadsheet_repository),
    notifications: UserNotificationRepository = Depends(get_user_notification_repository),
) -> NotificationService:
    """Сервис исходящих сообщений пользователю."""
    return NotificationService(session, spreadsheets, notifications=notifications)
