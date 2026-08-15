"""Эндпоинты чеков: очередь, кэш типов, запись разобранного чека."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.dependencies.services import get_check_service
from api.domain.check_item import CheckItem, ProductTypeAssignment
from api.requests.checks.commit_check_request import CommitCheckRequest
from api.requests.checks.enqueue_check_request import EnqueueCheckRequest
from api.responses.checks.cashed_record_response import CashedRecordResponse
from api.responses.checks.check_queue_item_response import CheckQueueItemResponse
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.records.record_response import RecordResponse
from api.services.check_service import CheckService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}", tags=["checks"])


@router.get("/checks-queue", response_model=ItemsResponse[CheckQueueItemResponse])
async def list_checks_queue(
    spreadsheet_id: int,
    service: CheckService = Depends(get_check_service),
) -> ItemsResponse[CheckQueueItemResponse]:
    """Чеки, ожидающие разбора."""
    items = await service.list_queue(spreadsheet_id)
    return ItemsResponse(items=[CheckQueueItemResponse.model_validate(item) for item in items])


@router.post(
    "/checks-queue",
    response_model=DataResponse[CheckQueueItemResponse],
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_check(
    spreadsheet_id: int,
    payload: EnqueueCheckRequest,
    service: CheckService = Depends(get_check_service),
) -> DataResponse[CheckQueueItemResponse]:
    """Кладёт сырой чек в очередь на разбор."""
    item = await service.enqueue(spreadsheet_id, payload.check_text)
    return DataResponse(data=CheckQueueItemResponse.model_validate(item))


@router.delete("/checks-queue/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_from_queue(
    spreadsheet_id: int,
    item_id: int,
    service: CheckService = Depends(get_check_service),
) -> None:
    """Убирает чек из очереди: пользователь его пропустил (`/skip`) или удалил."""
    await service.delete_from_queue(spreadsheet_id, item_id)


@router.get("/cashed-records", response_model=ItemsResponse[CashedRecordResponse])
async def list_cashed_records(
    spreadsheet_id: int,
    service: CheckService = Depends(get_check_service),
) -> ItemsResponse[CashedRecordResponse]:
    """Выученные соответствия «товар → тип».

    Бот берёт их, чтобы не спрашивать модель о товарах, которые уже встречались.
    """
    items = await service.list_cashed_records(spreadsheet_id)
    return ItemsResponse(items=[CashedRecordResponse.model_validate(item) for item in items])


@router.post(
    "/checks/commit",
    response_model=ItemsResponse[RecordResponse],
    status_code=status.HTTP_201_CREATED,
)
async def commit_check(
    spreadsheet_id: int,
    payload: CommitCheckRequest,
    service: CheckService = Depends(get_check_service),
) -> ItemsResponse[RecordResponse]:
    """Записывает разобранный чек целиком одной транзакцией.

    Стадии диалога, модель и подтверждения пользователя остаются в боте: они
    перемежаются вопросами и живут в его состоянии. Сюда приезжает готовый
    результат — новые типы товаров, кэш, N операций и снятие чека с очереди, и ни
    одна часть не может уцелеть без остальных.
    """
    records = await service.commit_check(
        spreadsheet_id,
        source_id=payload.source_id,
        items=[
            CheckItem(
                product_name=item.product_name,
                product_type=item.product_type,
                category_id=item.category_id,
                amount=item.amount,
            )
            for item in payload.items
        ],
        new_product_types=[
            ProductTypeAssignment(
                category_id=assignment.category_id,
                product_type=assignment.product_type,
            )
            for assignment in payload.new_product_types
        ],
        check_id=payload.check_id,
        check_json=payload.check_json,
    )
    return ItemsResponse(items=[RecordResponse.model_validate(item) for item in records])
