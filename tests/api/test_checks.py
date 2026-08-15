"""Тесты эндпоинтов чеков."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories

_SAVE_BODY = {
    "kind": "RU_FNS",
    "qr_raw": "t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp=698610272&n=1",
    "external_key": "7384440901402798:145:698610272",
    "raw_payload": {"code": 1, "data": {"json": {"items": [{"name": "молоко", "sum": 8990}]}}},
    "fetched_at": "2026-07-25T15:08:00+00:00",
}


async def test_check_is_saved_with_payload_intact(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Чек сохраняется, и расшифровка возвращается ровно той же."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/checks"
    saved = await client.post(base, json=_SAVE_BODY)
    assert saved.status_code == 201
    assert saved.json()["data"]["raw_payload"] == _SAVE_BODY["raw_payload"]

    listed = await client.get(base)
    assert [item["external_key"] for item in listed.json()["items"]] == [
        _SAVE_BODY["external_key"]
    ]


async def test_repeated_scan_is_409(client: AsyncClient, session: AsyncSession) -> None:
    """Повторный скан того же чека — 409 с внятной причиной, а не 500."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/checks"
    assert (await client.post(base, json=_SAVE_BODY)).status_code == 201

    repeated = await client.post(base, json=_SAVE_BODY)
    assert repeated.status_code == 409
    assert repeated.json()["details"]["reason"] == "check_already_saved"
    assert len((await client.get(base)).json()["items"]) == 1


async def test_unknown_check_kind_is_422(client: AsyncClient, session: AsyncSession) -> None:
    """Неизвестный вид чека отсекается схемой.

    Вид — нативный enum в БД, и строка мимо него дошла бы до вставки, где
    превратилась бы в невнятную ошибку драйвера.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/checks",
        json={**_SAVE_BODY, "kind": "RS_FISCAL"},
    )
    assert response.status_code == 422


async def test_commit_flow(client: AsyncClient, session: AsyncSession) -> None:
    """Разобранный чек записывается целиком: операции, кэш и типы товаров."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    food = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}"
    committed = await client.post(
        f"{base}/checks/commit",
        json={
            "source_id": source.id,
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
