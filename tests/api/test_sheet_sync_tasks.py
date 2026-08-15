"""Тесты служебных эндпоинтов очереди перерисовки листов."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import SheetTarget
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from tests import factories


async def test_claim_complete_cycle(client: AsyncClient, session: AsyncSession) -> None:
    """Забрать задачу, отчитаться, увидеть пустую очередь.

    `spreadsheet_id` в задаче обязателен: claim отдаёт задачи сразу по всем
    документам, и без него воркер не знал бы, что перерисовывать.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    tasks = SheetSyncTaskRepository(session)
    await tasks.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    claimed = await client.post("/api/v1/sheet-sync-tasks/claim")
    assert claimed.status_code == 200
    task = claimed.json()["items"][0]
    assert task["spreadsheet_id"] == spreadsheet.id
    assert task["target"] == "CATEGORIES"
    assert task["kind"] == "REDRAW"
    assert task["attempts"] == 0

    completed = await client.post(
        f"/api/v1/sheet-sync-tasks/{task['id']}/complete",
        json={"requested_at": task["requested_at"]},
    )
    assert completed.status_code == 204
    assert (await client.post("/api/v1/sheet-sync-tasks/claim")).json()["items"] == []


async def test_fail_returns_task_to_the_queue(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Неудача возвращает задачу в очередь и растит счётчик попыток."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await SheetSyncTaskRepository(session).enqueue(spreadsheet.id, SheetTarget.BILLS)
    await session.commit()

    task = (await client.post("/api/v1/sheet-sync-tasks/claim")).json()["items"][0]
    failed = await client.post(
        f"/api/v1/sheet-sync-tasks/{task['id']}/fail",
        json={"error": "Google вернул 429"},
    )
    assert failed.status_code == 204

    stored = (await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id))[0]
    assert stored.attempts == 1
    assert stored.last_error == "Google вернул 429"


async def test_complete_of_unknown_task_is_204(client: AsyncClient) -> None:
    """Отчёт по уже удалённой задаче — не ошибка: воркер мог повторить запрос."""
    response = await client.post(
        "/api/v1/sheet-sync-tasks/123456/complete",
        json={"requested_at": "2026-08-12T10:00:00+00:00"},
    )
    assert response.status_code == 204


async def test_fail_of_unknown_task_is_404(client: AsyncClient) -> None:
    """А вот неудача по несуществующей задаче — 404: считать попытки нечему."""
    response = await client.post(
        "/api/v1/sheet-sync-tasks/123456/fail",
        json={"error": "неважно"},
    )
    assert response.status_code == 404
