"""Тесты агрегата баланса счёта.

Баланс не хранится в БД, а считается от начального баланса, операций и
переводов. Тесты здесь закрывают два разных класса ошибок: неверную форму
запроса (декартово произведение) и потерю копеек (float вместо Decimal).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import now_in_timezone
from api.repositories.record_repository import RecordRepository
from api.repositories.source_repository import SourceRepository
from api.repositories.transfer_repository import TransferRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_balance_of_untouched_source_equals_start_balance(session: AsyncSession) -> None:
    """Без операций и переводов баланс равен начальному."""
    spreadsheet = await factories.create_spreadsheet(session)
    source = await factories.create_source(session, spreadsheet, start_balance=Decimal("1000.00"))
    await session.commit()

    assert spreadsheet.id is not None
    balances = await SourceRepository(session).balances(spreadsheet.id)

    assert [(item.title, item.balance) for item in balances] == [
        (source.title, Decimal("1000.00"))
    ]


async def test_balance_with_records_and_transfers_on_both_sides(session: AsyncSession) -> None:
    """Расчёт с операциями и переводами в обе стороны.

    Это главный тест формы запроса. Наивная реализация — три `LEFT JOIN` с
    `GROUP BY` — перемножила бы строки: три операции × два входящих перевода ×
    два исходящих дают двенадцать строк, и каждая сумма посчиталась бы кратно
    числу строк остальных таблиц. Только набор с несколькими строками в каждой
    из трёх таблиц ловит эту ошибку — на одной операции и одном переводе
    неправильный запрос даёт правильный ответ.

    Карта:  1000.00 − 31.50 (три операции) − 300.00 (ушло) + 75.00 (пришло) = 743.50
    Нал:       0.00 + 300.00 (пришло) − 75.00 (ушло)                        = 225.00
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    card = await factories.create_source(
        session, spreadsheet, title="Карта", start_balance=Decimal("1000.00")
    )
    cash = await factories.create_source(
        session, spreadsheet, title="Нал", start_balance=Decimal("0.00")
    )

    for _ in range(3):
        await factories.create_record(
            session, spreadsheet, period, category, card, amount=Decimal("-10.50")
        )
    await factories.create_transfer(
        session, spreadsheet, period, card, cash, amount=Decimal("200.00")
    )
    await factories.create_transfer(
        session, spreadsheet, period, card, cash, amount=Decimal("100.00")
    )
    await factories.create_transfer(
        session, spreadsheet, period, cash, card, amount=Decimal("50.00")
    )
    await factories.create_transfer(
        session, spreadsheet, period, cash, card, amount=Decimal("25.00")
    )
    await session.commit()

    assert spreadsheet.id is not None
    balances = {item.title: item.balance for item in await SourceRepository(session).balances(
        spreadsheet.id
    )}

    assert balances == {"Карта": Decimal("743.50"), "Нал": Decimal("225.00")}


async def test_kopeks_survive_the_aggregate(session: AsyncSession) -> None:
    """Копейки не теряются: суммирование идёт в NUMERIC, а не во float.

    Три покупки по 10.50 должны дать ровно 31.50. Прежняя схема хранила деньги
    в `DOUBLE PRECISION`, а статистика сворачивала суммы через `int()` — итог за
    месяц расходился с листом операций, причём расходы, будучи отрицательными,
    занижались систематически: `int(-31.50)` даёт `-31`.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet, start_balance=Decimal("0.00"))

    for _ in range(3):
        await factories.create_record(
            session, spreadsheet, period, category, source, amount=Decimal("-10.50")
        )
    await session.commit()

    assert source.id is not None
    balance = await SourceRepository(session).balance_of(source.id)

    assert balance is not None
    assert balance.balance == Decimal("-31.50")


async def test_soft_deleted_record_stops_affecting_balance(session: AsyncSession) -> None:
    """Мягко удалённая операция перестаёт влиять на баланс."""
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet, start_balance=Decimal("500.00"))
    record = await factories.create_record(
        session, spreadsheet, period, category, source, amount=Decimal("-100.00")
    )
    await session.commit()

    assert source.id is not None
    assert record.id is not None
    repository = SourceRepository(session)
    assert (await repository.balance_of(source.id)).balance == Decimal("400.00")  # type: ignore[union-attr]

    await RecordRepository(session).soft_delete(
        record.id, at=now_in_timezone(spreadsheet.timezone)
    )
    await session.commit()

    assert (await repository.balance_of(source.id)).balance == Decimal("500.00")  # type: ignore[union-attr]


async def test_soft_deleted_transfer_stops_affecting_both_sides(session: AsyncSession) -> None:
    """Мягко удалённый перевод возвращает деньги обоим счетам."""
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    card = await factories.create_source(
        session, spreadsheet, title="Карта", start_balance=Decimal("1000.00")
    )
    cash = await factories.create_source(
        session, spreadsheet, title="Нал", start_balance=Decimal("0.00")
    )
    transfer = await factories.create_transfer(
        session, spreadsheet, period, card, cash, amount=Decimal("300.00")
    )
    await session.commit()

    assert transfer.id is not None
    assert spreadsheet.id is not None
    await TransferRepository(session).soft_delete(
        transfer.id, at=now_in_timezone(spreadsheet.timezone)
    )
    await session.commit()

    balances = {item.title: item.balance for item in await SourceRepository(session).balances(
        spreadsheet.id
    )}
    assert balances == {"Карта": Decimal("1000.00"), "Нал": Decimal("0.00")}


async def test_balance_ignores_other_spreadsheets(session: AsyncSession) -> None:
    """Операции чужого документа не попадают в баланс."""
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    my_source = await factories.create_source(session, mine, start_balance=Decimal("100.00"))

    other_period = await factories.create_period(session, other)
    other_category = await factories.create_category(session, other)
    other_source = await factories.create_source(session, other, start_balance=Decimal("0.00"))
    await factories.create_record(
        session, other, other_period, other_category, other_source, amount=Decimal("-50.00")
    )
    await session.commit()

    assert my_source.id is not None
    balance = await SourceRepository(session).balance_of(my_source.id)

    assert balance is not None
    assert balance.balance == Decimal("100.00")
