"""Тесты агрегата баланса счёта.

Баланс не хранится в БД, а считается от начального баланса, операций и
переводов. Тесты здесь закрывают два разных класса ошибок: неверную форму
запроса (декартово произведение) и потерю копеек (float вместо Decimal).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import now_in_timezone
from api.enums import CategoryKind, Currency
from api.rates.base import RateUnavailableError
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


async def test_operation_in_another_currency_is_converted_to_the_account(
    session: AsyncSession,
) -> None:
    """Динарная трата с еврового счёта уменьшает остаток на её курс, а не на число.

    Это и есть смысл всей затеи: без конвертации «500» вычиталось бы из евро как
    пятьсот евро, хотя человек отдал пятьсот динаров — примерно четыре.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    source = await factories.create_source(
        session, spreadsheet, currency=Currency.EUR, start_balance=Decimal("1000.00")
    )
    await factories.create_record(
        session,
        spreadsheet,
        period,
        category,
        source,
        amount=Decimal("-500.00"),
        currency=Currency.RSD,
        added_at=period.start_date,
    )
    await factories.create_rate(
        session,
        base=Currency.RSD,
        quote=Currency.EUR,
        rate=Decimal("0.008532"),
        rate_date=period.start_date,
    )
    await session.commit()

    assert spreadsheet.id is not None
    balance = await SourceRepository(session).balance_of(source.id)  # type: ignore[arg-type]

    assert balance is not None
    # 1000 − 500 × 0.008532 = 995.734 → 995.73 после округления до копеек.
    assert balance.balance == Decimal("995.73")


async def test_rate_of_the_operation_day_is_used_not_the_latest(
    session: AsyncSession,
) -> None:
    """Каждая операция считается по курсу своего дня.

    Иначе вчерашний остаток менялся бы сам по себе от одного лишь хода времени,
    и сойтись с выпиской он не мог бы никогда.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    source = await factories.create_source(
        session, spreadsheet, currency=Currency.EUR, start_balance=Decimal("0.00")
    )
    first_day = period.start_date
    second_day = period.start_date + timedelta(days=1)

    for day in (first_day, second_day):
        await factories.create_record(
            session,
            spreadsheet,
            period,
            category,
            source,
            amount=Decimal("-100.00"),
            currency=Currency.USD,
            added_at=day,
        )
    await factories.create_rate(
        session, base=Currency.USD, quote=Currency.EUR, rate=Decimal("1"), rate_date=first_day
    )
    await factories.create_rate(
        session, base=Currency.USD, quote=Currency.EUR, rate=Decimal("2"), rate_date=second_day
    )
    await session.commit()

    balance = await SourceRepository(session).balance_of(source.id)  # type: ignore[arg-type]

    assert balance is not None
    # −100×1 в первый день и −100×2 во второй: курсы разные, дни разные.
    assert balance.balance == Decimal("-300.00")


async def test_cross_currency_transfer_converts_only_the_receiving_side(
    session: AsyncSession,
) -> None:
    """Списывается сумма как есть, зачисляется — по курсу.

    Сумма перевода выражена в валюте счёта-источника: это единственная валюта,
    которую называет пользователь. Конвертировать её на списании значило бы
    пересчитать то, что и так уже в нужной валюте.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    sender = await factories.create_source(
        session,
        spreadsheet,
        title="Евро",
        currency=Currency.EUR,
        start_balance=Decimal("1000.00"),
    )
    receiver = await factories.create_source(
        session,
        spreadsheet,
        title="Динары",
        currency=Currency.RSD,
        start_balance=Decimal("0.00"),
    )
    await factories.create_transfer(
        session, spreadsheet, period, sender, receiver, amount=Decimal("100.00")
    )
    await factories.create_rate(
        session,
        base=Currency.EUR,
        quote=Currency.RSD,
        rate=Decimal("117.05"),
        rate_date=period.start_date,
    )
    await session.commit()

    assert spreadsheet.id is not None
    balances = {
        item.title: item.balance for item in await SourceRepository(session).balances(
            spreadsheet.id
        )
    }

    assert balances["Евро"] == Decimal("900.00")
    assert balances["Динары"] == Decimal("11705.00")


async def test_requirements_cover_exactly_what_the_aggregate_reads(
    session: AsyncSession,
) -> None:
    """Список нужных курсов совпадает с тем, что спросит агрегат.

    Ключевой инвариант всей конвертации. Недостающий курс не даёт ошибки в SQL:
    подзапрос вернёт `NULL`, умножение — `NULL`, а `SUM` молча выбросит
    слагаемое. Остаток занизится ровно на эту операцию и ничем себя не выдаст,
    поэтому «что нужно» и «чем считать» обязаны собираться одним обходом.

    Одинаковая валюта в список не попадает: курса к себе самой не существует, он
    подставляется единицей прямо в запросе.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    euro = await factories.create_source(session, spreadsheet, title="Евро", currency=Currency.EUR)
    dinars = await factories.create_source(
        session, spreadsheet, title="Динары", currency=Currency.RSD
    )

    await factories.create_record(
        session, spreadsheet, period, category, euro,
        amount=Decimal("-10.00"), currency=Currency.RSD, added_at=period.start_date,
    )
    # Операция в валюте своего счёта курса не требует.
    await factories.create_record(
        session, spreadsheet, period, category, euro,
        amount=Decimal("-10.00"), currency=Currency.EUR, added_at=period.start_date,
    )
    await factories.create_transfer(
        session, spreadsheet, period, euro, dinars, amount=Decimal("5.00")
    )
    await session.commit()

    assert spreadsheet.id is not None
    requirements = await SourceRepository(session).balance_requirements(spreadsheet.id)

    assert requirements == {
        (Currency.RSD, Currency.EUR, period.start_date),
        (Currency.EUR, Currency.RSD, period.start_date),
    }


async def test_missing_rate_is_refused_not_quietly_dropped(
    session: AsyncSession,
) -> None:
    """Без курса подсчёт отказывает, а не выдаёт правдоподобное неверное число.

    Тест написан по следам настоящей ошибки в этой же ветке. Сначала суммы
    сворачивались через `COALESCE(SUM(...), 0)`, и остаток счёта с
    неконвертируемой динарной тратой выходил равным `1000.00` — ровно тем же
    числом, что и до траты. `NULL` от ненайденного курса молча выбрасывался
    `SUM`, а `COALESCE` дорисовывал ноль: ни ошибки, ни следа.

    Теперь такой остаток невыразим. Отказ повторяется задачей перерисовки, а в
    таблице до тех пор остаются прежние — верные — числа.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    source = await factories.create_source(
        session, spreadsheet, currency=Currency.EUR, start_balance=Decimal("1000.00")
    )
    await factories.create_record(
        session, spreadsheet, period, category, source,
        amount=Decimal("-500.00"), currency=Currency.RSD, added_at=period.start_date,
    )
    await session.commit()

    assert spreadsheet.id is not None
    with pytest.raises(RateUnavailableError):
        await SourceRepository(session).balances(spreadsheet.id)


async def test_account_without_conversion_is_unaffected_by_a_neighbour_missing_rate(
    session: AsyncSession,
) -> None:
    """Отказ касается только того счёта, которому курса не хватило.

    Рублёвый счёт с рублёвыми операциями курсов не требует вовсе: единица
    подставляется прямо в запросе, и соседний сломанный счёт на него не влияет.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    plain = await factories.create_source(
        session, spreadsheet, title="Рубли", currency=Currency.RUB,
        start_balance=Decimal("100.00"),
    )
    await factories.create_record(
        session, spreadsheet, period, category, plain,
        amount=Decimal("-40.00"), currency=Currency.RUB, added_at=period.start_date,
    )
    await session.commit()

    balance = await SourceRepository(session).balance_of(plain.id)  # type: ignore[arg-type]

    assert balance is not None
    assert balance.balance == Decimal("60.00")
