"""Тесты эндпоинтов периодов и статистики."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import today_in_timezone
from api.enums import CategoryKind
from tests import factories

_TIMEZONE = "Europe/Moscow"


async def test_current_route_is_not_shadowed(client: AsyncClient, session: AsyncSession) -> None:
    """`/periods/current` не перехватывается параметрическим маршрутом."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    await factories.create_period(session, spreadsheet, day=today_in_timezone(_TIMEZONE))
    await session.commit()

    response = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/periods/current")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "OPEN"


async def test_current_period_is_created_on_read(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Чтение текущего периода заводит его, если строки ещё нет.

    Второй запрос здесь не украшение: он ходит в базу отдельной сессией и
    поэтому ловит незакоммиченную вставку. Без коммита в сервисе первый ответ
    выглядел бы верным, а период не существовал бы.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    await session.commit()

    response = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/periods/current")
    assert response.status_code == 200

    period = response.json()["data"]
    assert period["status"] == "OPEN"
    today = today_in_timezone(_TIMEZONE).isoformat()
    assert period["start_date"] <= today < period["end_date"]

    listed = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/periods")
    assert [item["id"] for item in listed.json()["items"]] == [period["id"]]


async def test_statistics_are_daily_and_signed(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Статистика — суммы по категории и дню, знаковые и с копейками."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    period = await factories.create_period(
        session, spreadsheet, day=today_in_timezone(_TIMEZONE)
    )
    category = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    await factories.create_record(
        session, spreadsheet, period, category, amount=Decimal("-1234.56")
    )
    await session.commit()

    response = await client.get(
        f"/api/v1/spreadsheets/{spreadsheet.id}/periods/{period.id}/statistics"
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["category_id"] == category.id
    assert item["total"] == "-1234.56"
    assert item["day"] == str(period.start_date)


async def test_periods_are_listed(client: AsyncClient, session: AsyncSession) -> None:
    """Список периодов приезжает в конверте `items`."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True, timezone=_TIMEZONE)
    await factories.create_period(session, spreadsheet, day=today_in_timezone(_TIMEZONE))
    await session.commit()

    response = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/periods")
    assert len(response.json()["items"]) == 1
