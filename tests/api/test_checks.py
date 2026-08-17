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
    check = await factories.create_check(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}"
    committed = await client.post(
        f"{base}/checks/commit",
        json={
            "check_id": check.id,
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
    check = await factories.create_check(session, spreadsheet)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/checks/commit",
        json={"check_id": check.id, "source_id": source.id, "items": []},
    )
    assert response.status_code == 422


async def test_unprocessed_filter_hides_parsed_checks(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """`?unprocessed=true` отдаёт очередь разбора, а не весь архив чеков."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    first = await factories.create_check(session, spreadsheet, external_key="первый")
    second = await factories.create_check(session, spreadsheet, external_key="второй")
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}"
    committed = await client.post(
        f"{base}/checks/commit",
        json={
            "check_id": first.id,
            "source_id": source.id,
            "items": [
                {"product_name": "молоко", "category_id": category.id, "amount": "89.90"}
            ],
        },
    )
    assert committed.status_code == 201
    assert [item["check_id"] for item in committed.json()["items"]] == [first.id]

    queue = await client.get(f"{base}/checks", params={"unprocessed": True})
    assert [item["id"] for item in queue.json()["items"]] == [second.id]
    assert len((await client.get(f"{base}/checks")).json()["items"]) == 2


async def test_period_filter_returns_the_archive_of_that_month(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """`?period_id=` отдаёт архив месяца: разобранные чеки с расшифровкой целиком.

    По этой выборке `google_sheets_service` строит лист чеков, поэтому
    `raw_payload` обязан приезжать нетронутым — интерпретировать чек сервис не
    будет, он его архивирует.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    parsed = await factories.create_check(session, spreadsheet, external_key="разобран")
    await factories.create_check(session, spreadsheet, external_key="в очереди")
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}"
    committed = await client.post(
        f"{base}/checks/commit",
        json={
            "check_id": parsed.id,
            "source_id": source.id,
            "items": [
                {"product_name": "молоко", "category_id": category.id, "amount": "89.90"}
            ],
        },
    )
    assert committed.status_code == 201
    period_id = committed.json()["items"][0]["period_id"]

    archive = await client.get(f"{base}/checks", params={"period_id": period_id})
    items = archive.json()["items"]
    assert [item["id"] for item in items] == [parsed.id]
    assert items[0]["raw_payload"]["data"]["json"]["totalSum"] == 8990


async def test_queue_and_archive_filters_are_incompatible(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Оба фильтра сразу — 422, а не молча пустой список.

    Неразобранный чек операций не имеет и в месяц не попадает никогда: такой
    запрос — ошибка вызывающего, и отвечать на него пустотой значило бы её
    спрятать.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    await session.commit()

    response = await client.get(
        f"/api/v1/spreadsheets/{spreadsheet.id}/checks",
        params={"unprocessed": True, "period_id": period.id},
    )
    assert response.status_code == 422


async def test_repeated_commit_is_409(client: AsyncClient, session: AsyncSession) -> None:
    """Второй разбор того же чека — 409, а не вторая пачка операций."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    check = await factories.create_check(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}"
    body = {
        "check_id": check.id,
        "source_id": source.id,
        "items": [{"product_name": "молоко", "category_id": category.id, "amount": "89.90"}],
    }
    assert (await client.post(f"{base}/checks/commit", json=body)).status_code == 201

    repeated = await client.post(f"{base}/checks/commit", json=body)
    assert repeated.status_code == 409
    assert repeated.json()["details"]["reason"] == "check_already_processed"
    assert len((await client.get(f"{base}/records")).json()["items"]) == 1


async def test_zero_priced_item_is_accepted(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Позиция с нулевой ценой записывается: «второй товар в подарок» законен."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    check = await factories.create_check(session, spreadsheet)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/checks/commit",
        json={
            "check_id": check.id,
            "source_id": source.id,
            "items": [{"product_name": "подарок", "category_id": category.id, "amount": "0"}],
        },
    )
    assert response.status_code == 201
    assert [item["amount"] for item in response.json()["items"]] == ["0.00"]


async def test_unprocessed_check_is_deleted(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """`DELETE .../checks/{id}` убирает неразобранный чек; повтор — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    check = await factories.create_check(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/checks"
    assert (await client.delete(f"{base}/{check.id}")).status_code == 204
    assert (await client.get(base)).json()["items"] == []
    assert (await client.delete(f"{base}/{check.id}")).status_code == 404


async def test_processed_check_is_not_deleted(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Разобранный чек удалить нельзя: на него ссылаются операции реестра."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    check = await factories.create_check(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}"
    await client.post(
        f"{base}/checks/commit",
        json={
            "check_id": check.id,
            "source_id": source.id,
            "items": [{"product_name": "молоко", "category_id": category.id, "amount": "1.00"}],
        },
    )

    refused = await client.delete(f"{base}/checks/{check.id}")
    assert refused.status_code == 409
    assert refused.json()["details"]["reason"] == "check_already_processed"
