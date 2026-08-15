"""Тесты служебных эндпоинтов соответствия «адресат → лист»."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories


async def test_upsert_and_list(client: AsyncClient, session: AsyncSession) -> None:
    """Повторная запись обновляет запись, а не добавляет вторую."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/sheet-mappings"
    first = await client.post(
        base,
        json={"target": "CATEGORIES", "google_sheet_id": 11, "title": "Categories"},
    )
    assert first.status_code == 200

    await client.post(
        base,
        json={"target": "CATEGORIES", "google_sheet_id": 22, "title": "Categories"},
    )

    items = (await client.get(base)).json()["items"]
    assert [(item["target"], item["google_sheet_id"]) for item in items] == [
        ("CATEGORIES", 22)
    ]


async def test_period_sheet_without_period_is_422(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Лист периода без периода — 422: адресат и период должны быть согласованы."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/sheet-mappings",
        json={"target": "OPERATIONS", "google_sheet_id": 1, "title": "2026-07-15"},
    )
    assert response.status_code == 422


async def test_period_sheet_with_period(client: AsyncClient, session: AsyncSession) -> None:
    """С периодом — записывается."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/sheet-mappings",
        json={
            "target": "STATISTICS",
            "google_sheet_id": 7,
            "title": "Stat. 2026-07-15",
            "period_id": period.id,
        },
    )
    assert response.status_code == 200
    assert response.json()["data"]["period_id"] == period.id
