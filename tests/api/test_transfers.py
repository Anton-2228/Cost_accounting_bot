"""Тесты эндпоинтов переводов."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories


async def test_transfer_moves_money_and_keeps_totals(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Перевод меняет балансы и не попадает в доходы и расходы."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(
        session, spreadsheet, title="Кошелёк", start_balance=Decimal("500.00")
    )
    card = await factories.create_source(session, spreadsheet, title="Карта")
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/transfers",
        json={"from_source_id": wallet.id, "to_source_id": card.id, "amount": "200.00"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["amount"] == "200.00"

    balances = {
        item["source_id"]: item["balance"]
        for item in (
            await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/balances")
        ).json()["items"]
    }
    assert balances[wallet.id] == "300.00"
    assert balances[card.id] == "200.00"

    period_id = response.json()["data"]["period_id"]
    statistics = await client.get(
        f"/api/v1/spreadsheets/{spreadsheet.id}/periods/{period_id}/statistics"
    )
    assert statistics.json()["items"] == []


async def test_transfer_to_itself_is_422(client: AsyncClient, session: AsyncSession) -> None:
    """Перевод на тот же счёт — 422 бизнес-правила, а не ошибка формата."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(session, spreadsheet)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/transfers",
        json={"from_source_id": wallet.id, "to_source_id": wallet.id, "amount": "10.00"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "business_rule_violation"


async def test_delete_last_transfer(client: AsyncClient, session: AsyncSession) -> None:
    """`/transfers/last` объявлен до `/transfers/{transfer_id}`."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    wallet = await factories.create_source(session, spreadsheet, start_balance=Decimal("50.00"))
    card = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/transfers"
    created = await client.post(
        base,
        json={"from_source_id": wallet.id, "to_source_id": card.id, "amount": "20.00"},
    )
    transfer_id = created.json()["data"]["id"]

    deleted = await client.delete(f"{base}/last")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["id"] == transfer_id
    assert (await client.get(base)).json()["items"] == []
