"""Тесты репозитория периодов: идемпотентность и догон пропусков."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import catch_up_starts, now_in_timezone, period_bounds, period_end
from api.enums import PeriodStatus
from api.repositories.period_repository import PeriodRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_ensure_is_idempotent(session: AsyncSession) -> None:
    """Повторный вызов возвращает тот же период, а не создаёт второй.

    На этом стоит весь ролловер: его можно запускать сколько угодно раз, в том
    числе после сбоя на середине.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = PeriodRepository(session)

    first = await repository.ensure(spreadsheet.id, date(2026, 7, 15), date(2026, 8, 15))
    second = await repository.ensure(spreadsheet.id, date(2026, 7, 15), date(2026, 8, 15))
    await session.commit()

    assert first.id == second.id
    assert len(await repository.list_by_spreadsheet(spreadsheet.id)) == 1


async def test_rollover_catches_up_every_missed_month(session: AsyncSession) -> None:
    """Многомесячный простой не теряет ни одного периода.

    Воспроизводит сценарий: последний период открыт 15 марта, сервис не работал
    до 20 июля. Старый ролловер сравнивал `today != end_date` точным равенством
    и пропускал месяц навсегда.
    """
    spreadsheet = await factories.create_spreadsheet(session, reset_day=15)
    assert spreadsheet.id is not None
    repository = PeriodRepository(session)

    start, end = period_bounds(date(2026, 3, 20), spreadsheet.reset_day)
    await repository.ensure(spreadsheet.id, start, end)
    await session.commit()

    for missed_start in catch_up_starts(start, today=date(2026, 7, 20)):
        await repository.ensure(spreadsheet.id, missed_start, period_end(missed_start))
    await session.commit()

    periods = await repository.list_by_spreadsheet(spreadsheet.id)
    assert [item.start_date for item in periods] == [
        date(2026, 3, 15),
        date(2026, 4, 15),
        date(2026, 5, 15),
        date(2026, 6, 15),
        date(2026, 7, 15),
    ]


async def test_get_containing_uses_half_open_bounds(session: AsyncSession) -> None:
    """День `end_date` принадлежит следующему периоду, а не текущему."""
    spreadsheet = await factories.create_spreadsheet(session, reset_day=15)
    assert spreadsheet.id is not None
    repository = PeriodRepository(session)

    july = await repository.ensure(spreadsheet.id, date(2026, 7, 15), date(2026, 8, 15))
    august = await repository.ensure(spreadsheet.id, date(2026, 8, 15), date(2026, 9, 15))
    await session.commit()

    assert (await repository.get_containing(spreadsheet.id, date(2026, 7, 15))).id == july.id  # type: ignore[union-attr]
    assert (await repository.get_containing(spreadsheet.id, date(2026, 8, 14))).id == july.id  # type: ignore[union-attr]
    assert (await repository.get_containing(spreadsheet.id, date(2026, 8, 15))).id == august.id  # type: ignore[union-attr]


async def test_close_is_idempotent(session: AsyncSession) -> None:
    """Повторное закрытие не переписывает момент первого."""
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    await session.commit()

    assert period.id is not None
    repository = PeriodRepository(session)
    moment = now_in_timezone(spreadsheet.timezone)

    assert await repository.close(period.id, at=moment) is True
    await session.commit()
    assert await repository.close(period.id, at=moment) is False

    stored = await repository.get_by_id(period.id)
    assert stored is not None
    assert stored.status is PeriodStatus.CLOSED


async def test_get_latest_returns_most_recent(session: AsyncSession) -> None:
    """Последний период — самый поздний по дате начала, а не по id."""
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = PeriodRepository(session)

    await repository.ensure(spreadsheet.id, date(2026, 8, 15), date(2026, 9, 15))
    await repository.ensure(spreadsheet.id, date(2026, 6, 15), date(2026, 7, 15))
    await session.commit()

    latest = await repository.get_latest(spreadsheet.id)
    assert latest is not None
    assert latest.start_date == date(2026, 8, 15)
