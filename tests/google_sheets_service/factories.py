"""Фабрики структур api для тестов сервиса синхронизации."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from google_sheets_service.main_api.dto import (
    Access,
    Category,
    CategoryDailyTotal,
    Check,
    Period,
    Record,
    SheetMapping,
    Source,
    SourceBalance,
    Spreadsheet,
    SyncTask,
    Transfer,
)

#: Период по умолчанию: август 2026 целиком. Границы полуинтервальные, поэтому
#: первое сентября в него не входит и колонки не получает.
PERIOD_START = date(2026, 8, 1)
PERIOD_END = date(2026, 9, 1)


def make_task(
    *,
    task_id: int = 1,
    spreadsheet_id: int = 1,
    kind: str = "REDRAW",
    target: str = "CATEGORIES",
    period_id: int | None = None,
    attempts: int = 0,
) -> SyncTask:
    """Задача очереди."""
    return SyncTask(
        id=task_id,
        spreadsheet_id=spreadsheet_id,
        kind=kind,
        target=target,
        period_id=period_id,
        requested_at=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        attempts=attempts,
    )


#: Момент создания строки таблицы. Входит в метку документа в Drive, поэтому
#: значение фиксировано: метка обязана быть одной и той же между повторами.
SPREADSHEET_CREATED_AT = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


def make_spreadsheet(
    *,
    spreadsheet_id: int = 1,
    google_spreadsheet_id: str | None = "google-1",
    created_at: datetime = SPREADSHEET_CREATED_AT,
) -> Spreadsheet:
    """Учётная таблица."""
    return Spreadsheet(
        id=spreadsheet_id,
        google_spreadsheet_id=google_spreadsheet_id,
        title="Проверка",
        reset_day=1,
        timezone="Europe/Moscow",
        created_at=created_at,
    )


def make_period(
    *,
    period_id: int = 7,
    start_date: date = PERIOD_START,
    end_date: date = PERIOD_END,
    status: str = "OPEN",
) -> Period:
    """Учётный период."""
    return Period(id=period_id, start_date=start_date, end_date=end_date, status=status)


def make_category(
    *,
    category_id: int = 1,
    kind: str = "EXPENSE",
    status: str = "ACTIVE",
    title: str = "Еда",
    associations: list[str] | None = None,
    product_types: list[str] | None = None,
) -> Category:
    """Категория."""
    return Category(
        id=category_id,
        kind=kind,
        status=status,
        title=title,
        associations=associations if associations is not None else [title.lower()],
        product_types=product_types if product_types is not None else [],
    )


def make_source(
    *,
    source_id: int = 1,
    status: str = "ACTIVE",
    title: str = "Карта",
    associations: list[str] | None = None,
    currency: str = "RUB",
    start_balance: str = "1000.00",
) -> Source:
    """Счёт."""
    return Source(
        id=source_id,
        status=status,
        title=title,
        associations=associations if associations is not None else [title.lower()],
        currency=currency,
        start_balance=Decimal(start_balance),
    )


def make_balance(
    *,
    source_id: int = 1,
    title: str = "Карта",
    start_balance: str = "1000.00",
    balance: str = "850.50",
) -> SourceBalance:
    """Посчитанный баланс счёта."""
    return SourceBalance(
        source_id=source_id,
        title=title,
        start_balance=Decimal(start_balance),
        balance=Decimal(balance),
    )


def make_record(
    *,
    record_id: int = 1,
    period_id: int = 7,
    category_id: int = 1,
    source_id: int = 1,
    amount: str = "-149.50",
    currency: str = "RUB",
    added_at: date = PERIOD_START,
    notes: str = "",
    product_name: str | None = "Хлеб",
    product_type: str | None = "выпечка",
    check_id: int | None = None,
) -> Record:
    """Операция."""
    return Record(
        id=record_id,
        period_id=period_id,
        category_id=category_id,
        source_id=source_id,
        amount=Decimal(amount),
        currency=currency,
        added_at=added_at,
        notes=notes,
        product_name=product_name,
        product_type=product_type,
        check_id=check_id,
    )


def make_check(
    *,
    check_id: int = 1,
    raw_payload: dict[str, Any] | None = None,
) -> Check:
    """Разобранный чек для листа-архива."""
    return Check(
        id=check_id,
        raw_payload=raw_payload if raw_payload is not None else {"data": {"json": {
            "totalSum": 12100,
            "items": [{"name": "Молоко 3.2%", "sum": 8990}],
        }}},
    )


def make_transfer(
    *,
    transfer_id: int = 1,
    period_id: int = 7,
    from_source_id: int = 1,
    to_source_id: int = 2,
    amount: str = "500.00",
    added_at: date = PERIOD_START,
    notes: str = "",
) -> Transfer:
    """Перевод между счетами."""
    return Transfer(
        id=transfer_id,
        period_id=period_id,
        from_source_id=from_source_id,
        to_source_id=to_source_id,
        amount=Decimal(amount),
        added_at=added_at,
        notes=notes,
    )


def make_total(
    *,
    category_id: int = 1,
    day: date = PERIOD_START,
    total: str = "-149.50",
) -> CategoryDailyTotal:
    """Дневной итог по категории."""
    return CategoryDailyTotal(category_id=category_id, day=day, total=Decimal(total))


def make_mapping(
    *,
    mapping_id: int = 1,
    target: str = "CATEGORIES",
    period_id: int | None = None,
    google_sheet_id: int = 11,
    title: str = "Categories",
) -> SheetMapping:
    """Соответствие «адресат → лист»."""
    return SheetMapping(
        id=mapping_id,
        target=target,
        period_id=period_id,
        google_sheet_id=google_sheet_id,
        title=title,
    )


def make_access(
    *,
    access_id: int = 1,
    email: str = "user@example.com",
    role: str = "WRITER",
) -> Access:
    """Невыданный доступ."""
    return Access(id=access_id, email=email, role=role, granted_at=None)
