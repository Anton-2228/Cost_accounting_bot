"""Фикстуры сервисного слоя.

Сервисы собираются на той же сессии, что и репозитории, — так же, как это делают
зависимости FastAPI. Поэтому тест видит ровно ту транзакционную границу, что и
эндпоинт: коммитит только сервис.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.check_repository import CheckRepository
from api.repositories.exchange_rate_repository import ExchangeRateRepository
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
from api.services.exchange_rate_service import ExchangeRateService
from api.services.notification_service import NotificationService
from api.services.period_service import PeriodService
from api.services.record_service import RecordService
from api.services.rollover_service import RolloverService
from api.services.sheet_mapping_service import SheetMappingService
from api.services.sheet_sync_task_service import SheetSyncTaskService
from api.services.source_import_service import SourceImportService
from api.services.spreadsheet_service import SpreadsheetService
from api.services.transfer_service import TransferService
from tests.fakes import FakeRateProvider


@pytest.fixture
def rate_provider() -> FakeRateProvider:
    """Источник курсов, отвечающий из таблицы вместо сети.

    Отдельной фикстурой, а не внутри сервиса: тестам конвертации нужно и
    заряжать курсы, и потом смотреть, сколько раз за ними ходили.

    Курс по умолчанию — единица. Тесты, написанные не про валюту, так остаются
    про то, про что написаны: лист статистики сводится к евро, и без дефолта
    даже проверка знака у рублёвой операции требовала бы подготовки курсов.
    Тесты конвертации задают свои курсы явно и на единицу не полагаются.
    """
    return FakeRateProvider(default_rate=Decimal("1"))


@pytest.fixture
def rate_service(session: AsyncSession, rate_provider: FakeRateProvider) -> ExchangeRateService:
    """Сервис дозагрузки курсов."""
    return ExchangeRateService(session, ExchangeRateRepository(session), rate_provider)


@pytest.fixture
def spreadsheet_service(
    session: AsyncSession,
    rate_service: ExchangeRateService,
) -> SpreadsheetService:
    """Сервис жизненного цикла документа."""
    return SpreadsheetService(
        session,
        SpreadsheetRepository(session),
        users=UserRepository(session),
        periods=PeriodRepository(session),
        categories=CategoryRepository(session),
        sources=SourceRepository(session),
        accesses=SpreadsheetAccessRepository(session),
        tasks=SheetSyncTaskRepository(session),
        notifications=UserNotificationRepository(session),
        rates=rate_service,
    )


@pytest.fixture
def record_service(session: AsyncSession) -> RecordService:
    """Сервис операций."""
    return RecordService(
        session,
        SpreadsheetRepository(session),
        periods=PeriodRepository(session),
        categories=CategoryRepository(session),
        sources=SourceRepository(session),
        records=RecordRepository(session),
        cashed_records=CashedRecordRepository(session),
        checks=CheckRepository(session),
        tasks=SheetSyncTaskRepository(session),
    )


@pytest.fixture
def transfer_service(session: AsyncSession) -> TransferService:
    """Сервис переводов."""
    return TransferService(
        session,
        SpreadsheetRepository(session),
        periods=PeriodRepository(session),
        sources=SourceRepository(session),
        transfers=TransferRepository(session),
        tasks=SheetSyncTaskRepository(session),
    )


@pytest.fixture
def check_service(session: AsyncSession) -> CheckService:
    """Сервис чеков."""
    return CheckService(
        session,
        SpreadsheetRepository(session),
        periods=PeriodRepository(session),
        categories=CategoryRepository(session),
        sources=SourceRepository(session),
        records=RecordRepository(session),
        cashed_records=CashedRecordRepository(session),
        checks=CheckRepository(session),
        tasks=SheetSyncTaskRepository(session),
    )


@pytest.fixture
def period_service(session: AsyncSession, rate_service: ExchangeRateService) -> PeriodService:
    """Сервис чтения периодов."""
    return PeriodService(
        session,
        SpreadsheetRepository(session),
        periods=PeriodRepository(session),
        records=RecordRepository(session),
        rates=rate_service,
    )


@pytest.fixture
def category_import_service(session: AsyncSession) -> CategoryImportService:
    """Сервис импорта листа `Categories`."""
    return CategoryImportService(
        session,
        SpreadsheetRepository(session),
        categories=CategoryRepository(session),
        periods=PeriodRepository(session),
        cashed_records=CashedRecordRepository(session),
        tasks=SheetSyncTaskRepository(session),
        notifications=UserNotificationRepository(session),
    )


@pytest.fixture
def source_import_service(session: AsyncSession) -> SourceImportService:
    """Сервис импорта листа `Bills`."""
    return SourceImportService(
        session,
        SpreadsheetRepository(session),
        sources=SourceRepository(session),
        periods=PeriodRepository(session),
        tasks=SheetSyncTaskRepository(session),
        notifications=UserNotificationRepository(session),
    )


@pytest.fixture
def rollover_service(session: AsyncSession) -> RolloverService:
    """Сервис смены учётного месяца."""
    return RolloverService(
        session,
        SpreadsheetRepository(session),
        periods=PeriodRepository(session),
        tasks=SheetSyncTaskRepository(session),
        notifications=UserNotificationRepository(session),
    )


@pytest.fixture
def sheet_sync_task_service(session: AsyncSession) -> SheetSyncTaskService:
    """Сервис очереди перерисовки листов."""
    return SheetSyncTaskService(
        session,
        SheetSyncTaskRepository(session),
        UserNotificationRepository(session),
    )


@pytest.fixture
def sheet_mapping_service(session: AsyncSession) -> SheetMappingService:
    """Сервис соответствий «адресат → лист»."""
    return SheetMappingService(
        session,
        SpreadsheetRepository(session),
        mappings=SheetMappingRepository(session),
        periods=PeriodRepository(session),
    )


@pytest.fixture
def notification_service(session: AsyncSession) -> NotificationService:
    """Сервис уведомлений."""
    return NotificationService(
        session,
        SpreadsheetRepository(session),
        notifications=UserNotificationRepository(session),
    )
