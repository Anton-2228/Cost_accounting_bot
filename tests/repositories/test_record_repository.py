"""Тесты репозитория операций."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import now_in_timezone
from api.enums import Currency
from api.repositories.record_repository import RecordRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_records_are_selected_by_period_not_by_date_range(session: AsyncSession) -> None:
    """Операции отбираются по внешнему ключу периода, а не по диапазону дат.

    Поэтому операция в граничный день не может оказаться сразу в двух периодах,
    как это было при включительном `BETWEEN`.
    """
    spreadsheet = await factories.create_spreadsheet(session, reset_day=15)
    july = await factories.create_period(session, spreadsheet, day=date(2026, 7, 20))
    august = await factories.create_period(session, spreadsheet, day=date(2026, 8, 20))
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)

    # Дата 15 августа — граница: конец июльского периода и начало августовского.
    await factories.create_record(
        session, spreadsheet, august, category, source,
        amount=Decimal("-10.00"), added_at=date(2026, 8, 15),
    )
    await session.commit()

    repository = RecordRepository(session)
    assert july.id is not None
    assert august.id is not None
    assert await repository.list_by_period(july.id) == []
    assert len(await repository.list_by_period(august.id)) == 1


async def test_soft_deleted_record_leaves_the_listing(session: AsyncSession) -> None:
    """Удалённая операция исчезает из выборки, но остаётся в БД для разбора."""
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    record = await factories.create_record(
        session, spreadsheet, period, category, source, amount=Decimal("-10.00")
    )
    await session.commit()

    assert record.id is not None
    assert period.id is not None
    repository = RecordRepository(session)
    await repository.soft_delete(record.id, at=now_in_timezone(spreadsheet.timezone))
    await session.commit()

    assert await repository.list_by_period(period.id) == []
    assert len(await repository.list_by_period(period.id, include_deleted=True)) == 1
    assert await repository.count_by_period(period.id) == 0


async def test_soft_delete_is_idempotent(session: AsyncSession) -> None:
    """Повторное удаление возвращает False и не переписывает метку времени.

    Без условия `deleted_at IS NULL` повтор исказил бы хронологию и отрапортовал
    об успехе там, где ничего не изменилось.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    record = await factories.create_record(
        session, spreadsheet, period, category, source, amount=Decimal("-10.00")
    )
    await session.commit()

    assert record.id is not None
    repository = RecordRepository(session)
    moment = now_in_timezone(spreadsheet.timezone)

    assert await repository.soft_delete(record.id, at=moment) is True
    await session.commit()
    first = await repository.get_by_id(record.id, include_deleted=True)

    assert await repository.soft_delete(record.id, at=moment) is False
    await session.commit()
    second = await repository.get_by_id(record.id, include_deleted=True)

    assert first is not None and second is not None
    assert first.deleted_at == second.deleted_at


async def test_get_last_in_period_skips_deleted(session: AsyncSession) -> None:
    """«Последняя операция» не указывает на уже удалённую.

    Прежний код брал последний элемент списка периода и при повторе команды
    удалял другую, ещё живую запись.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    first = await factories.create_record(
        session, spreadsheet, period, category, source, amount=Decimal("-10.00")
    )
    last = await factories.create_record(
        session, spreadsheet, period, category, source, amount=Decimal("-20.00")
    )
    await session.commit()

    assert last.id is not None
    assert period.id is not None
    repository = RecordRepository(session)
    await repository.soft_delete(last.id, at=now_in_timezone(spreadsheet.timezone))
    await session.commit()

    remaining = await repository.get_last_in_period(period.id)
    assert remaining is not None
    assert remaining.id == first.id


async def test_daily_totals_keep_kopeks(session: AsyncSession) -> None:
    """Дневные итоги считаются в Decimal и группируются по дням.

    Прежний код сворачивал их через `int()`: копейки терялись, а расходы,
    будучи отрицательными, занижались систематически.
    """
    spreadsheet = await factories.create_spreadsheet(session, reset_day=15)
    period = await factories.create_period(session, spreadsheet, day=date(2026, 7, 20))
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)

    await factories.create_record(
        session, spreadsheet, period, category, source,
        amount=Decimal("-10.50"), added_at=date(2026, 7, 20),
    )
    await factories.create_record(
        session, spreadsheet, period, category, source,
        amount=Decimal("-5.25"), added_at=date(2026, 7, 20),
    )
    await factories.create_record(
        session, spreadsheet, period, category, source,
        amount=Decimal("-1.01"), added_at=date(2026, 7, 21),
    )
    await session.commit()

    assert period.id is not None
    totals = await RecordRepository(session).daily_totals_by_category(period.id, base=Currency.RUB)

    assert [(item.day, item.total) for item in totals] == [
        (date(2026, 7, 20), Decimal("-15.75")),
        (date(2026, 7, 21), Decimal("-1.01")),
    ]


async def test_get_for_spreadsheet_rejects_foreign_record(session: AsyncSession) -> None:
    """Операция чужого документа не отдаётся."""
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, other)
    category = await factories.create_category(session, other)
    source = await factories.create_source(session, other)
    record = await factories.create_record(
        session, other, period, category, source, amount=Decimal("-10.00")
    )
    await session.commit()

    assert record.id is not None
    assert mine.id is not None
    assert await RecordRepository(session).get_for_spreadsheet(record.id, mine.id) is None
