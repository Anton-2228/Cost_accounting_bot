"""Тесты чтения периодов и дневных итогов."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import today_in_timezone
from api.enums import CategoryKind, Currency
from api.exceptions.base import NotFoundError
from api.rates.base import RateUnavailableError
from api.repositories.period_repository import PeriodRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services.period_service import PeriodService
from tests import factories
from tests.fakes import FakeRateProvider

_TIMEZONE = "Europe/Moscow"


async def test_current_period_is_not_created_by_reading(
    session: AsyncSession,
    period_service: PeriodService,
) -> None:
    """Чтение не создаёт период: 404 вместо молчаливой записи.

    Период создают операция (лениво) и ролловер. Иначе GET менял бы данные, а
    открытый период появлялся бы от одного лишь просмотра архива.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    await session.commit()
    assert spreadsheet.id is not None

    with pytest.raises(NotFoundError):
        await period_service.current(spreadsheet.id)

    assert await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id) == []


async def test_periods_are_listed_in_order(
    session: AsyncSession,
    period_service: PeriodService,
) -> None:
    """Периоды отдаются по возрастанию даты начала."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    today = today_in_timezone(_TIMEZONE)
    await factories.create_period(session, spreadsheet, day=today)
    await factories.create_period(session, spreadsheet, day=today - timedelta(days=40))
    await session.commit()
    assert spreadsheet.id is not None

    periods = await period_service.list_all(spreadsheet.id)
    assert [item.start_date for item in periods] == sorted(item.start_date for item in periods)

    current = await period_service.current(spreadsheet.id)
    assert current.contains(today)


async def test_periods_of_unlinked_spreadsheet_are_still_listed(
    session: AsyncSession,
    period_service: PeriodService,
) -> None:
    """Отвязанный документ отдаёт свои периоды, а не 404.

    Ровно этим чтением отчёт о тратах на модель раскладывает их по учётным
    периодам, а траты считаются по **всем** таблицам пользователя, включая
    отвязанные: деньги потрачены независимо от того, ведёт ли он учёт дальше.
    Пока чтение шло через проверку живости, админ получал на первой же такой
    таблице «Сначала создайте таблицу» вместо отчёта.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    today = today_in_timezone(_TIMEZONE)
    await factories.create_period(session, spreadsheet, day=today)
    await session.commit()
    assert spreadsheet.id is not None

    await SpreadsheetRepository(session).soft_delete(
        spreadsheet.id, at=datetime.now(tz=UTC)
    )
    await session.commit()

    periods = await period_service.list_all(spreadsheet.id)
    assert len(periods) == 1


async def test_periods_of_unknown_spreadsheet_are_404(
    period_service: PeriodService,
) -> None:
    """Несуществующий документ по-прежнему 404: терпимость только к мягкому удалению."""
    with pytest.raises(NotFoundError):
        await period_service.list_all(10_000)


async def test_daily_totals_keep_kopecks_and_sign(
    session: AsyncSession,
    period_service: PeriodService,
) -> None:
    """Дневные итоги знаковые и не округлены.

    Прежний код сворачивал их через `int()`: копейки терялись, а расходы —
    отрицательные — систематически занижались, ведь `int(-1234.56)` даёт `-1234`.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    period = await factories.create_period(
        session, spreadsheet, day=today_in_timezone(_TIMEZONE)
    )
    expense = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    income = await factories.create_category(session, spreadsheet, kind=CategoryKind.INCOME)
    source = await factories.create_source(session, spreadsheet)
    for amount, category in (
        (Decimal("-1234.56"), expense),
        (Decimal("-0.44"), expense),
        (Decimal("500.10"), income),
    ):
        await factories.create_record(
            session, spreadsheet, period, category, source, amount=amount
        )
    await session.commit()
    assert spreadsheet.id is not None and expense.id is not None and income.id is not None

    totals = {
        item.category_id: item.total
        for item in await period_service.daily_totals(spreadsheet.id, period.id)
    }
    assert totals[expense.id] == Decimal("-1235.00")
    assert totals[income.id] == Decimal("500.10")


async def test_statistics_of_alien_period_is_not_found(
    session: AsyncSession,
    period_service: PeriodService,
) -> None:
    """Статистика чужого периода — 404, а не пустой список."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    stranger = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    alien_period = await factories.create_period(session, stranger)
    await session.commit()
    assert spreadsheet.id is not None and alien_period.id is not None

    with pytest.raises(NotFoundError):
        await period_service.daily_totals(spreadsheet.id, alien_period.id)


async def test_statistics_are_converted_to_one_currency(
    session: AsyncSession,
    period_service: PeriodService,
    rate_provider: FakeRateProvider,
) -> None:
    """Операции в разных валютах сводятся к одной, иначе итог не значит ничего.

    Лист статистики складывает суммы по категории за день. Складывать динары с
    евро бессмысленно, поэтому всё приводится к
    :data:`api.core.constants.STATISTICS_CURRENCY`.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    source = await factories.create_source(session, spreadsheet, currency=Currency.EUR)
    for currency in (Currency.EUR, Currency.RSD):
        await factories.create_record(
            session,
            spreadsheet,
            period,
            category,
            source,
            amount=Decimal("-100.00"),
            currency=currency,
            added_at=period.start_date,
        )
    await session.commit()
    assert spreadsheet.id is not None

    rate_provider.add(Currency.RSD, period.start_date, {Currency.EUR: Decimal("0.01")})
    totals = await period_service.daily_totals(spreadsheet.id, period.id)

    # −100 евро как есть и −100 динаров по одной сотой = −1 евро.
    assert [item.total for item in totals] == [Decimal("-101.00")]


async def test_statistics_convert_the_original_amount_not_via_the_account(
    session: AsyncSession,
    period_service: PeriodService,
    rate_provider: FakeRateProvider,
) -> None:
    """Исходная сумма переводится в валюту статистики напрямую.

    Через валюту счёта было бы два округления вместо одного, и копейки терялись
    бы на каждом шаге. Здесь счёт рублёвый, операция динарная, статистика в
    евро — и курс нужен ровно один: RSD→EUR.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    source = await factories.create_source(session, spreadsheet, currency=Currency.RUB)
    await factories.create_record(
        session,
        spreadsheet,
        period,
        category,
        source,
        amount=Decimal("-1000.00"),
        currency=Currency.RSD,
        added_at=period.start_date,
    )
    await session.commit()
    assert spreadsheet.id is not None

    rate_provider.add(Currency.RSD, period.start_date, {Currency.EUR: Decimal("0.0085")})
    totals = await period_service.daily_totals(spreadsheet.id, period.id)

    assert [item.total for item in totals] == [Decimal("-8.50")]
    assert rate_provider.calls == [(Currency.RSD, period.start_date)]


async def test_statistics_refuse_to_count_without_a_rate(
    session: AsyncSession,
    period_service: PeriodService,
    rate_provider: FakeRateProvider,
) -> None:
    """Недоступный курс роняет подсчёт, а не выдаёт часть суммы.

    Задача перерисовки листа повторится позже, а до тех пор в таблице останутся
    прежние верные числа.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    source = await factories.create_source(session, spreadsheet, currency=Currency.RUB)
    await factories.create_record(
        session,
        spreadsheet,
        period,
        category,
        source,
        amount=Decimal("-1000.00"),
        currency=Currency.RSD,
        added_at=period.start_date,
    )
    await session.commit()
    assert spreadsheet.id is not None

    rate_provider.default_rate = None
    with pytest.raises(RateUnavailableError):
        await period_service.daily_totals(spreadsheet.id, period.id)
