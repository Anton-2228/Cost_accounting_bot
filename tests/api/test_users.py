"""Тесты эндпоинтов пользователя целиком, а не одного документа."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories

_PREFIX = "/api/v1/users"


async def test_history_includes_unlinked_spreadsheets(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """История отдаёт и отвязанные документы, и живой.

    Это и есть смысл маршрута: деньги, ушедшие на модель, потрачены независимо
    от того, ведёт ли пользователь учёт по документу до сих пор. Живой документ
    отличается от отвязанного пустым `deleted_at`.
    """
    user = await factories.create_user(session, telegram_id=7101)
    old = await factories.create_spreadsheet(session, user=user, title="Старая", ready=True)
    await session.commit()
    assert old.id is not None
    await client.delete(f"/api/v1/spreadsheets/{old.id}")
    await factories.create_spreadsheet(session, user=user, title="Текущая", ready=True)
    await session.commit()

    response = await client.get(f"{_PREFIX}/7101/spreadsheets")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["title"] for item in items] == ["Старая", "Текущая"]
    assert items[0]["deleted_at"] is not None
    assert items[1]["deleted_at"] is None


async def test_current_spreadsheet_route_still_hides_unlinked(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """`by-telegram` продолжает отвечать только про живой документ.

    Два маршрута отвечают на разные вопросы, и смешать их нельзя: по этому боту
    выбирает, с чем работать сейчас, и отвязанный документ здесь означал бы
    операции, уходящие в брошенную таблицу.
    """
    user = await factories.create_user(session, telegram_id=7102)
    spreadsheet = await factories.create_spreadsheet(session, user=user, ready=True)
    await session.commit()
    assert spreadsheet.id is not None
    await client.delete(f"/api/v1/spreadsheets/{spreadsheet.id}")

    history = await client.get(f"{_PREFIX}/7102/spreadsheets")
    current = await client.get("/api/v1/spreadsheets/by-telegram/7102")

    assert len(history.json()["items"]) == 1
    assert current.status_code == 404


async def test_user_without_spreadsheets_gets_empty_list(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Пользователь без документов — это пустой список, а не ошибка."""
    await factories.create_user(session, telegram_id=7103)
    await session.commit()

    response = await client.get(f"{_PREFIX}/7103/spreadsheets")

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_unknown_user_is_404_with_resource(client: AsyncClient) -> None:
    """Неизвестный telegram_id — 404 по ресурсу `user`.

    Отличать его от пустого списка обязательно: иначе опечатка в
    идентификаторе выглядела бы как «этот человек ничего не тратил». Ресурс в
    `details` — то, по чему бот подбирает русский текст.
    """
    response = await client.get(f"{_PREFIX}/999999/spreadsheets")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["details"] == {"resource": "user"}
