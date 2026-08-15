"""Тесты операций реестра."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import now_in_timezone, today_in_timezone
from api.domain.cashed_record import CashedRecord
from api.enums import CategoryKind, SheetTarget
from api.exceptions.base import BusinessRuleError, NotFoundError
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.source_repository import SourceRepository
from api.services.record_service import RecordService
from tests import factories


async def test_expense_is_stored_with_negative_amount(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Знак ставит вид категории, а не клиент.

    Сумма приходит по модулю. Прежде знак приезжал вместе с суммой, и расход с
    минусом превращался в доход.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    record = await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("100.50"),
    )

    assert record.amount == Decimal("-100.50")
    assert record.added_at == today_in_timezone(spreadsheet.timezone)


async def test_income_is_stored_positive(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Доход остаётся положительным."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.INCOME)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    record = await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("100.50"),
    )
    assert record.amount == Decimal("100.50")


async def test_record_marks_three_sheets_stale(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Операция устаревает реестр, статистику и балансы — три листа сразу."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("10.00"),
    )

    targets = {
        task.target
        for task in await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    }
    assert targets == {SheetTarget.OPERATIONS, SheetTarget.STATISTICS, SheetTarget.BILLS}


async def test_ten_records_leave_one_task_per_sheet(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Десять операций подряд не дают десять перерисовок одного листа.

    Задача описывает устаревание, а не изменение, поэтому повторная постановка
    только двигает `requested_at`.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    for _ in range(10):
        await record_service.create(
            spreadsheet.id,
            category_id=category.id,
            source_id=source.id,
            amount=Decimal("1.00"),
        )

    tasks = await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert len(tasks) == 3


async def test_period_is_created_lazily(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Период создаётся первой же операцией, а не только ролловером.

    Иначе после простоя сервиса пользователь не смог бы сделать вообще ничего:
    операции запрещены в закрытый период, а нового ещё нет.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None
    assert await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id) == []

    record = await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("5.00"),
    )

    periods = await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert len(periods) == 1
    assert periods[0].id == record.period_id
    assert periods[0].contains(record.added_at)


async def test_zero_and_negative_amounts_are_rejected(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Ноль и минус отвергаются: знак — дело категории, а нулевой операции нет смысла."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    for amount in (Decimal("0.00"), Decimal("-1.00")):
        with pytest.raises(BusinessRuleError):
            await record_service.create(
                spreadsheet.id,
                category_id=category.id,
                source_id=source.id,
                amount=amount,
            )


async def test_category_of_another_document_is_not_found(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Категорию чужого документа указать нельзя.

    В БД это невыразимо благодаря составным внешним ключам; сервис отвечает 404,
    не доводя дело до ошибки целостности.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    stranger = await factories.create_spreadsheet(session, ready=True)
    alien_category = await factories.create_category(session, stranger)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None
    assert alien_category.id is not None and source.id is not None

    with pytest.raises(NotFoundError):
        await record_service.create(
            spreadsheet.id,
            category_id=alien_category.id,
            source_id=source.id,
            amount=Decimal("1.00"),
        )


async def test_delete_last_forgets_learned_product_type(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Удаление операции стирает выученный тип её товара.

    Кэш учится на подтверждённых операциях. Удалили операцию — подтверждения
    больше нет, и следующий чек должен спросить тип заново, а не повторить ошибку.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    cache = CashedRecordRepository(session)
    await cache.upsert(
        CashedRecord(
            spreadsheet_id=spreadsheet.id,
            product_name="молоко",
            product_type="продукты",
        )
    )
    record = await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("50.00"),
        product_name="молоко",
        product_type="продукты",
    )

    deleted = await record_service.delete(spreadsheet.id)
    assert deleted.id == record.id
    assert await cache.get(spreadsheet.id, "молоко") is None


async def test_delete_is_soft_and_balance_recovers(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Удаление мягкое, а баланс пересчитывается сам: он не хранится."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet, start_balance=Decimal("1000.00"))
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    record = await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("250.00"),
    )
    assert record.id is not None

    sources = SourceRepository(session)
    balance = await sources.balance_of(source.id)
    assert balance is not None
    assert balance.balance == Decimal("750.00")

    await record_service.delete(spreadsheet.id, record.id)

    stored = await RecordRepository(session).get_for_spreadsheet(
        record.id, spreadsheet.id, include_deleted=True
    )
    assert stored is not None
    assert stored.deleted_at is not None

    balance = await sources.balance_of(source.id)
    assert balance is not None
    assert balance.balance == Decimal("1000.00")


async def test_record_of_closed_period_is_not_deletable(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Закрытый месяц не меняется: удаление задним числом — 422.

    Закрытие означает «месяц сдан», а удаление поменяло бы итоги, которые
    пользователь уже видел.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    record = await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("10.00"),
    )
    assert record.id is not None

    periods = PeriodRepository(session)
    assert await periods.close(record.period_id, at=now_in_timezone(spreadsheet.timezone))
    await session.commit()

    with pytest.raises(BusinessRuleError):
        await record_service.delete(spreadsheet.id, record.id)


async def test_delete_last_without_records_is_not_found(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Удалять нечего — 404, а не молчаливый успех."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    with pytest.raises(NotFoundError):
        await record_service.delete(spreadsheet.id)


async def test_list_by_period_defaults_to_current_and_checks_owner(
    session: AsyncSession,
    record_service: RecordService,
) -> None:
    """Без периода отдаётся текущий; чужой период — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    stranger = await factories.create_spreadsheet(session, ready=True)
    alien_period = await factories.create_period(session, stranger, day=date(2026, 8, 1))
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None
    assert alien_period.id is not None

    assert await record_service.list_by_period(spreadsheet.id) == []

    record = await record_service.create(
        spreadsheet.id,
        category_id=category.id,
        source_id=source.id,
        amount=Decimal("7.00"),
    )
    current = await record_service.list_by_period(spreadsheet.id)
    assert [item.id for item in current] == [record.id]
    assert [item.id for item in await record_service.list_by_period(
        spreadsheet.id, record.period_id
    )] == [record.id]

    with pytest.raises(NotFoundError):
        await record_service.list_by_period(spreadsheet.id, alien_period.id)
