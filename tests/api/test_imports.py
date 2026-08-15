"""Тесты служебных эндпоинтов импорта листов."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories


async def test_categories_import_creates_and_reports_counts(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Импорт возвращает, что именно он сделал."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/import/categories",
        json={"rows": [["", "1", "0", "1", "Еда", "продукты", "продукты"]]},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "error": None,
        "created": 1,
        "updated": 0,
        "deleted": 0,
    }

    categories = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/categories")
    assert [item["title"] for item in categories.json()["items"]] == ["Еда"]


async def test_broken_sheet_returns_200_with_russian_error(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Ошибка разбора листа едет как данные, а не как код ошибки.

    Она собрана из содержимого листа и номера строки, поэтому 200 и текст в
    поле: бот печатает его как есть. Ошибка не в запросе — она в таблице
    пользователя.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/import/bills",
        json={"rows": [["", "1", "Карта", "", "много", ""]]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["error"] == "В источниках в 1 строке Balance не число"

    sources = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/sources")
    assert sources.json()["items"] == []

    notifications = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/notifications")
    assert [item["kind"] for item in notifications.json()["items"]] == ["IMPORT_ERROR"]


async def test_bills_import_ignores_current_balance_column(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Колонка `Current balance` с листа не читается."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/import/bills",
        json={"rows": [["", "1", "Карта", "сбер", "100", "99999"]]},
    )

    balances = await client.get(f"/api/v1/spreadsheets/{spreadsheet.id}/balances")
    assert balances.json()["items"][0]["balance"] == "100.00"
