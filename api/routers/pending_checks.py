"""Эндпоинты отложенных чеков: список, повтор, удаление и отчёты фона.

Внешний сервис расшифровки api не зовёт — это делает `checks_service`. Здесь
только учёт: что отложено, кто сейчас спрашивает и когда спросить снова.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from api.core import constants
from api.dependencies.services import get_pending_check_service
from api.requests.pending_checks.add_pending_check_request import AddPendingCheckRequest
from api.requests.pending_checks.fail_pending_check_request import FailPendingCheckRequest
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.pending_checks.pending_check_response import PendingCheckResponse
from api.services.pending_check_service import PendingCheckService

router = APIRouter(tags=["pending-checks"])


@router.post("/pending-checks/claim", response_model=ItemsResponse[PendingCheckResponse])
async def claim_due(
    limit: int = Query(default=constants.PENDING_CHECK_CLAIM_LIMIT, ge=1),
    service: PendingCheckService = Depends(get_pending_check_service),
) -> ItemsResponse[PendingCheckResponse]:
    """Забирает чеки, которым пора повторить запрос (служебное, для фона).

    POST, а не GET: запрос помечает строки забранными, чтобы их не взял второй
    воркер или ручной повтор.
    """
    items = await service.claim_due(limit)
    return ItemsResponse(items=[PendingCheckResponse.model_validate(item) for item in items])


@router.post("/pending-checks/{pending_id}/fail", status_code=status.HTTP_204_NO_CONTENT)
async def fail(
    pending_id: int,
    payload: FailPendingCheckRequest,
    service: PendingCheckService = Depends(get_pending_check_service),
) -> None:
    """Отчёт о неудачной попытке: снимает захват и назначает следующую.

    Удачной попытке отдельный отчёт не нужен: сохранённый чек
    (`POST /spreadsheets/{id}/checks`) сам убирает отложенный. Строки уже нет —
    тоже 204: чек успели сохранить или удалить, пока шла попытка.
    """
    await service.fail(
        pending_id,
        payload.error,
        manual=payload.manual,
        notice=None if payload.notice is None else payload.notice.to_domain(),
    )


@router.get(
    "/spreadsheets/{spreadsheet_id}/pending-checks",
    response_model=ItemsResponse[PendingCheckResponse],
)
async def list_pending(
    spreadsheet_id: int,
    service: PendingCheckService = Depends(get_pending_check_service),
) -> ItemsResponse[PendingCheckResponse]:
    """Отложенные чеки документа в порядке сканирования, истёкшие тоже."""
    items = await service.list_pending(spreadsheet_id)
    return ItemsResponse(items=[PendingCheckResponse.model_validate(item) for item in items])


@router.post(
    "/spreadsheets/{spreadsheet_id}/pending-checks",
    response_model=DataResponse[PendingCheckResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_pending(
    spreadsheet_id: int,
    payload: AddPendingCheckRequest,
    service: PendingCheckService = Depends(get_pending_check_service),
) -> DataResponse[PendingCheckResponse]:
    """Откладывает чек. Повторный скан того же чека вернёт ту же строку."""
    pending = await service.add(
        spreadsheet_id,
        kind=payload.kind,
        qr_raw=payload.qr_raw,
        external_key=payload.external_key,
        error=payload.error,
    )
    return DataResponse(data=PendingCheckResponse.model_validate(pending))


@router.post(
    "/spreadsheets/{spreadsheet_id}/pending-checks/{pending_id}/claim",
    response_model=DataResponse[PendingCheckResponse],
)
async def claim_one(
    spreadsheet_id: int,
    pending_id: int,
    service: PendingCheckService = Depends(get_pending_check_service),
) -> DataResponse[PendingCheckResponse]:
    """Забирает чек для ручного повтора; занятый — 409 `pending_check_busy`."""
    pending = await service.claim(spreadsheet_id, pending_id)
    return DataResponse(data=PendingCheckResponse.model_validate(pending))


@router.delete(
    "/spreadsheets/{spreadsheet_id}/pending-checks/{pending_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_pending(
    spreadsheet_id: int,
    pending_id: int,
    service: PendingCheckService = Depends(get_pending_check_service),
) -> None:
    """Убирает отложенный чек: фон о нём больше не спрашивает."""
    await service.delete(spreadsheet_id, pending_id)
