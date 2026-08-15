"""Тесты эндпоинтов чеков."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories


async def test_queue_and_commit_flow(client: AsyncClient, session: AsyncSession) -> None:
    """Чек кладётся в очередь, записывается целиком и уходит из очереди."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    food = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}"
    queued = await client.post(f"{base}/checks-queue", json={"check_text": "сырой чек"})
    assert queued.status_code == 201
    check_id = queued.json()["data"]["id"]

    queue = await client.get(f"{base}/checks-queue")
    assert [item["id"] for item in queue.json()["items"]] == [check_id]

    committed = await client.post(
        f"{base}/checks/commit",
        json={
            "source_id": source.id,
            "check_id": check_id,
            "items": [
                {
                    "product_name": "молоко",
                    "product_type": "продукты",
                    "category_id": food.id,
                    "amount": "89.90",
                },
                {
                    "product_name": "хлеб",
                    "product_type": "продукты",
                    "category_id": food.id,
                    "amount": "40.10",
                },
            ],
            "new_product_types": [{"category_id": food.id, "product_type": "продукты"}],
        },
    )
    assert committed.status_code == 201
    assert [item["amount"] for item in committed.json()["items"]] == ["-89.90", "-40.10"]

    assert (await client.get(f"{base}/checks-queue")).json()["items"] == []

    cached = await client.get(f"{base}/cashed-records")
    assert {item["product_name"] for item in cached.json()["items"]} == {"молоко", "хлеб"}

    categories = await client.get(f"{base}/categories")
    assert categories.json()["items"][0]["product_types"] == ["продукты"]


async def test_commit_without_items_is_422(client: AsyncClient, session: AsyncSession) -> None:
    """Чек без позиций — 422: записывать нечего."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/checks/commit",
        json={"source_id": source.id, "items": []},
    )
    assert response.status_code == 422


async def test_skip_removes_check_from_queue(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Пропуск чека убирает его из очереди; повтор — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/checks-queue"
    queued = await client.post(base, json={"check_text": "чек"})
    check_id = queued.json()["data"]["id"]

    assert (await client.delete(f"{base}/{check_id}")).status_code == 204
    assert (await client.delete(f"{base}/{check_id}")).status_code == 404
