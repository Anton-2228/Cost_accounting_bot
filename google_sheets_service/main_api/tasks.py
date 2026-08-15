"""Клиент очереди перерисовки листов."""

from __future__ import annotations

import httpx

from google_sheets_service.main_api.dto import SyncTask
from google_sheets_service.main_api.http import ApiHttpClient


class TasksApiClient:
    """Забирает задачи и отчитывается об их исходе."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def claim(self, limit: int) -> list[SyncTask]:
        """Забирает пачку созревших задач.

        Метод POST, а не GET: запрос меняет состояние — помечает задачи
        забранными, чтобы их не взял второй воркер.
        """
        items = await self._http.post_items(
            f"/sheet-sync-tasks/claim?limit={limit}",
            expected=httpx.codes.OK,
        )
        return [SyncTask.from_json(item) for item in items]

    async def complete(self, task: SyncTask) -> None:
        """Отмечает задачу выполненной.

        `requested_at` возвращается ровно таким, каким пришёл: по нему api
        видит, не устарел ли лист снова, пока его рисовали.
        """
        await self._http.post_empty(
            f"/sheet-sync-tasks/{task.id}/complete",
            body={"requested_at": task.requested_at.isoformat()},
        )

    async def fail(self, task: SyncTask, error: str, *, terminal: bool = False) -> None:
        """Возвращает задачу в очередь с паузой.

        `terminal` означает, что повтор получит тот же ответ: документ удалён,
        доступ отозван. Api тогда сразу уведомит пользователя, а не после пятой
        попытки.
        """
        await self._http.post_empty(
            f"/sheet-sync-tasks/{task.id}/fail",
            body={"error": error, "terminal": terminal},
        )
