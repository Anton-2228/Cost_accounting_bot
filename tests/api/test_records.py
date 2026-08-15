"""Тесты эндпоинтов операций."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import now_in_timezone
from api.enums import CategoryKind
from api.repositories.period_repository import PeriodRepository
from tests import factories


async def test_expense_and_income_get_their_sign(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Клиент присылает модуль, знак ставит вид категории."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    expense = await factories.create_category(session, spreadsheet, kind=CategoryKind.EXPENSE)
    income = await factories.create_category(session, spreadsheet, kind=CategoryKind.INCOME)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/records"
    spent = await client.post(
        base,
        json={"category_id": expense.id, "source_id": source.id, "amount": "100.50"},
    )
    assert spent.status_code == 201
    assert spent.json()["data"]["amount"] == "-100.50"
    assert spent.json()["data"]["from_check"] is False

    earned = await client.post(
        base,
        json={"category_id": income.id, "source_id": source.id, "amount": "100.50"},
    )
    assert earned.json()["data"]["amount"] == "100.50"


async def test_negative_amount_is_rejected_by_schema(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Отрицательная сумма не проходит схему: знак — не дело клиента."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/records",
        json={"category_id": category.id, "source_id": source.id, "amount": "-5.00"},
    )
    assert response.status_code == 422


async def test_receipt_json_is_not_exposed_in_list(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Сырой чек наружу не выдаётся, вместо него — признак `from_check`.

    Иначе список операций за месяц вырос бы до нескольких мегабайт: JSON лежит в
    каждой позиции чека целиком.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/records"
    await client.post(
        base,
        json={
            "category_id": category.id,
            "source_id": source.id,
            "amount": "10.00",
            "product_name": "молоко",
            "check_json": "{\"very\": \"long\"}",
        },
    )

    items = (await client.get(base)).json()["items"]
    assert [item["from_check"] for item in items] == [True]
    assert "check_json" not in items[0]


async def test_last_route_is_declared_before_id_route(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """`/records/last` не перехватывается маршрутом `/records/{record_id}`.

    Иначе литерал `last` попал бы в параметр пути и превратился в 422.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/records"
    created = await client.post(
        base,
        json={"category_id": category.id, "source_id": source.id, "amount": "7.00"},
    )
    record_id = created.json()["data"]["id"]

    deleted = await client.delete(f"{base}/last")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["id"] == record_id

    assert (await client.get(base)).json()["items"] == []
    assert (await client.delete(f"{base}/{record_id}")).status_code == 404


async def test_deleting_record_of_closed_period_is_422(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Закрытый месяц не меняется: 422 с кодом бизнес-правила."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/records"
    created = await client.post(
        base,
        json={"category_id": category.id, "source_id": source.id, "amount": "7.00"},
    )
    record = created.json()["data"]

    periods = PeriodRepository(session)
    assert await periods.close(
        record["period_id"], at=now_in_timezone(spreadsheet.timezone)
    )
    await session.commit()

    response = await client.delete(f"{base}/{record['id']}")
    assert response.status_code == 422
    assert response.json()["code"] == "business_rule_violation"


async def test_list_by_explicit_period(client: AsyncClient, session: AsyncSession) -> None:
    """Лист операций перерисовывается по конкретному периоду.

    Тот же эндпоинт без параметра отдаёт текущий период — им пользуется бот.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/records"
    created = await client.post(
        base,
        json={"category_id": category.id, "source_id": source.id, "amount": "3.00"},
    )
    period_id = created.json()["data"]["period_id"]

    by_period = await client.get(base, params={"period_id": period_id})
    assert [item["amount"] for item in by_period.json()["items"]] == ["-3.00"]

    alien = await client.get(base, params={"period_id": period_id + 1000})
    assert alien.status_code == 404


async def test_balance_follows_records(client: AsyncClient, session: AsyncSession) -> None:
    """Баланс счёта уменьшается ровно на сумму расхода: он считается, не хранится."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(
        session, spreadsheet, start_balance=Decimal("1000.00")
    )
    await session.commit()

    await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/records",
        json={"category_id": category.id, "source_id": source.id, "amount": "250.25"},
    )

    balances = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/balances")
    assert balances.json()["items"][0]["balance"] == "749.75"
