"""Эндпоинты очереди перерисовки листов (служебные, для gsheets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from api.core import constants
from api.dependencies.services import get_sheet_sync_task_service
from api.requests.sheet_sync_tasks.complete_task_request import CompleteTaskRequest
from api.requests.sheet_sync_tasks.fail_task_request import FailTaskRequest
from api.responses.common.items_response import ItemsResponse
from api.responses.sheet_sync_tasks.sheet_sync_task_response import SheetSyncTaskResponse
from api.services.sheet_sync_task_service import SheetSyncTaskService

router = APIRouter(prefix="/sheet-sync-tasks", tags=["service"])


@router.post("/claim", response_model=ItemsResponse[SheetSyncTaskResponse])
async def claim_tasks(
    limit: int = Query(default=constants.SHEET_SYNC_CLAIM_LIMIT, ge=1),
    service: SheetSyncTaskService = Depends(get_sheet_sync_task_service),
) -> ItemsResponse[SheetSyncTaskResponse]:
    """Забирает пачку созревших задач.

    Метод POST, а не GET: запрос меняет состояние — помечает задачи забранными,
    чтобы их не взял второй воркер.
    """
    tasks = await service.claim(limit)
    return ItemsResponse(items=[SheetSyncTaskResponse.model_validate(task) for task in tasks])


@router.post("/{task_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_task(
    task_id: int,
    payload: CompleteTaskRequest,
    service: SheetSyncTaskService = Depends(get_sheet_sync_task_service),
) -> None:
    """Отмечает задачу выполненной.

    Ответ 204 в обоих случаях. Если за время работы лист изменили снова, задача
    остаётся в очереди и освобождается для следующего захода — для воркера это не
    ошибка, а нормальный ход дел: он просто увидит её в следующем `claim`.
    """
    await service.complete(task_id, payload.requested_at)


@router.post("/{task_id}/fail", status_code=status.HTTP_204_NO_CONTENT)
async def fail_task(
    task_id: int,
    payload: FailTaskRequest,
    service: SheetSyncTaskService = Depends(get_sheet_sync_task_service),
) -> None:
    """Возвращает задачу в очередь с экспоненциальной паузой.

    Пока попыток немного, пользователю не сообщаем: недоступность Google обычно
    проходит сама. Дальше уходит уведомление — иначе он смотрит на застывшую
    таблицу и не понимает, почему она не обновляется.

    С `terminal=true` пауза сразу длинная, а уведомление уходит с первой же
    попытки: ответ Google не изменится, пока пользователь не вмешается. Задача
    при этом остаётся в очереди — доступ могут вернуть.
    """
    await service.fail(task_id, payload.error, terminal=payload.terminal)
