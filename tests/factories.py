"""Фабрики тестовых данных.

Написаны вручную и идут через настоящие репозитории, а не через прямые вставки:
так фабрика заодно проверяет, что репозиторий вообще способен создать сущность.
Уникальные значения выдаёт `itertools.count`, поэтому тесты не спотыкаются об
уникальные ключи.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import period_bounds
from api.domain.category import Category
from api.domain.check import Check
from api.domain.period import Period
from api.domain.record import Record
from api.domain.source import Source
from api.domain.spreadsheet import Spreadsheet
from api.domain.transfer import Transfer
from api.domain.user import User
from api.enums import CategoryKind, CheckKind
from api.repositories.category_repository import CategoryRepository
from api.repositories.check_repository import CheckRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_repository import UserRepository

_telegram_ids = itertools.count(1000)
_titles = itertools.count(1)
_google_ids = itertools.count(1)
_checks = itertools.count(1)


async def create_user(session: AsyncSession, *, telegram_id: int | None = None) -> User:
    """Создаёт пользователя."""
    return await UserRepository(session).add(
        User(telegram_id=telegram_id if telegram_id is not None else next(_telegram_ids))
    )


async def create_spreadsheet(
    session: AsyncSession,
    *,
    user: User | None = None,
    title: str = "Тест",
    reset_day: int = 15,
    timezone: str = "Europe/Moscow",
    ready: bool = False,
) -> Spreadsheet:
    """Создаёт учётную таблицу вместе с владельцем, если он не передан.

    `ready=True` сразу проставляет `google_spreadsheet_id`, то есть делает
    документ «готовым»: без него сервисы отвечают 409
    `spreadsheet_not_ready`, и почти любой тест бизнес-логики упирался бы в эту
    проверку вместо того, что он проверяет.
    """
    owner = user if user is not None else await create_user(session)
    assert owner.id is not None
    repository = SpreadsheetRepository(session)
    spreadsheet = await repository.add(
        Spreadsheet(
            user_id=owner.id,
            title=title,
            reset_day=reset_day,
            timezone=timezone,
        )
    )
    if not ready:
        return spreadsheet

    assert spreadsheet.id is not None
    updated = await repository.set_google_spreadsheet_id(
        spreadsheet.id, f"google-{next(_google_ids)}"
    )
    assert updated is not None
    return updated


async def create_period(
    session: AsyncSession,
    spreadsheet: Spreadsheet,
    *,
    day: date | None = None,
) -> Period:
    """Создаёт период, содержащий указанную дату."""
    assert spreadsheet.id is not None
    anchor = day if day is not None else date(2026, 7, 20)
    start_date, end_date = period_bounds(anchor, spreadsheet.reset_day)
    return await PeriodRepository(session).ensure(spreadsheet.id, start_date, end_date)


async def create_category(
    session: AsyncSession,
    spreadsheet: Spreadsheet,
    *,
    title: str | None = None,
    kind: CategoryKind = CategoryKind.EXPENSE,
    associations: list[str] | None = None,
    product_types: list[str] | None = None,
) -> Category:
    """Создаёт категорию вместе с псевдонимами и типами товаров."""
    assert spreadsheet.id is not None
    name = title if title is not None else f"Категория{next(_titles)}"
    return await CategoryRepository(session).add(
        Category(
            spreadsheet_id=spreadsheet.id,
            kind=kind,
            title=name,
            associations=associations if associations is not None else [name.lower()],
            product_types=product_types or [],
        )
    )


async def create_source(
    session: AsyncSession,
    spreadsheet: Spreadsheet,
    *,
    title: str | None = None,
    start_balance: Decimal = Decimal("0.00"),
    associations: list[str] | None = None,
) -> Source:
    """Создаёт счёт."""
    assert spreadsheet.id is not None
    name = title if title is not None else f"Счёт{next(_titles)}"
    return await SourceRepository(session).add(
        Source(
            spreadsheet_id=spreadsheet.id,
            title=name,
            start_balance=start_balance,
            associations=associations if associations is not None else [name.lower()],
        )
    )


async def create_check(
    session: AsyncSession,
    spreadsheet: Spreadsheet,
    *,
    external_key: str | None = None,
    raw_payload: dict[str, object] | None = None,
) -> Check:
    """Создаёт неразобранный чек с минимальным правдоподобным сырьём ФНС."""
    assert spreadsheet.id is not None
    key = external_key if external_key is not None else f"7384440901402798:145:{next(_checks)}"
    return await CheckRepository(session).add(
        Check(
            spreadsheet_id=spreadsheet.id,
            kind=CheckKind.RU_FNS,
            qr_raw=f"t=20260725T1507&s=89.90&fn=7384440901402798&i=145&fp={key}&n=1",
            external_key=key,
            raw_payload=raw_payload
            if raw_payload is not None
            else {
                "code": 1,
                "data": {
                    "json": {
                        "operationType": 1,
                        "totalSum": 8990,
                        "retailPlace": "Магазин",
                        "items": [{"name": "молоко", "sum": 8990}],
                    }
                },
            },
            fetched_at=datetime(2026, 7, 25, 15, 8, tzinfo=UTC),
        )
    )


async def create_record(
    session: AsyncSession,
    spreadsheet: Spreadsheet,
    period: Period,
    category: Category,
    source: Source,
    *,
    amount: Decimal,
    added_at: date | None = None,
    notes: str = "",
    check_id: int | None = None,
) -> Record:
    """Создаёт операцию. Сумма знаковая: расход отрицателен."""
    assert spreadsheet.id is not None
    assert period.id is not None
    assert category.id is not None
    assert source.id is not None
    return await RecordRepository(session).add(
        Record(
            spreadsheet_id=spreadsheet.id,
            period_id=period.id,
            category_id=category.id,
            source_id=source.id,
            amount=amount,
            added_at=added_at if added_at is not None else period.start_date,
            notes=notes,
            check_id=check_id,
        )
    )


async def create_transfer(
    session: AsyncSession,
    spreadsheet: Spreadsheet,
    period: Period,
    from_source: Source,
    to_source: Source,
    *,
    amount: Decimal,
    added_at: date | None = None,
) -> Transfer:
    """Создаёт перевод. Сумма строго положительна, направление задают счета."""
    assert spreadsheet.id is not None
    assert period.id is not None
    assert from_source.id is not None
    assert to_source.id is not None
    from api.repositories.transfer_repository import TransferRepository

    return await TransferRepository(session).add(
        Transfer(
            spreadsheet_id=spreadsheet.id,
            period_id=period.id,
            from_source_id=from_source.id,
            to_source_id=to_source.id,
            amount=amount,
            added_at=added_at if added_at is not None else period.start_date,
        )
    )
