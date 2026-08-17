"""Эндпоинты операций реестра."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.dependencies.services import get_record_service
from api.requests.records.create_record_request import CreateRecordRequest
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.records.record_response import RecordResponse
from api.services.record_service import RecordService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}/records", tags=["records"])


@router.get("", response_model=ItemsResponse[RecordResponse])
async def list_records(
    spreadsheet_id: int,
    period_id: int | None = None,
    service: RecordService = Depends(get_record_service),
) -> ItemsResponse[RecordResponse]:
    """Операции периода; без `period_id` — текущего.

    Один эндпоинт на два клиента: бот спрашивает «мои операции» без параметра, а
    `google_sheets_service` перерисовывает конкретный лист и указывает период.
    """
    records = await service.list_by_period(spreadsheet_id, period_id)
    return ItemsResponse(items=[RecordResponse.model_validate(item) for item in records])


@router.post(
    "",
    response_model=DataResponse[RecordResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_record(
    spreadsheet_id: int,
    payload: CreateRecordRequest,
    service: RecordService = Depends(get_record_service),
) -> DataResponse[RecordResponse]:
    """Добавляет операцию.

    Сумма приходит без знака, знак ставит вид категории. Период определяется
    сегодняшней датой в часовом поясе документа и создаётся, если его ещё нет.
    """
    record = await service.create(
        spreadsheet_id,
        category_id=payload.category_id,
        source_id=payload.source_id,
        amount=payload.amount,
        notes=payload.notes,
        product_name=payload.product_name,
        product_type=payload.product_type,
    )
    return DataResponse(data=RecordResponse.model_validate(record))


@router.delete("/last", response_model=DataResponse[RecordResponse])
async def delete_last_record(
    spreadsheet_id: int,
    service: RecordService = Depends(get_record_service),
) -> DataResponse[RecordResponse]:
    """Удаляет последнюю операцию текущего периода (команда `/del`).

    Объявлен до `/{record_id}`, иначе литерал `last` был бы разобран как
    идентификатор и превратился в 422.

    Удалённая операция возвращается: боту есть что показать пользователю, а
    именно её он и просил убрать.
    """
    record = await service.delete(spreadsheet_id)
    return DataResponse(data=RecordResponse.model_validate(record))


@router.delete("/{record_id}", response_model=DataResponse[RecordResponse])
async def delete_record(
    spreadsheet_id: int,
    record_id: int,
    service: RecordService = Depends(get_record_service),
) -> DataResponse[RecordResponse]:
    """Удаляет операцию по идентификатору.

    Удаление мягкое: разобраться в спорном балансе после ошибочного `/del` иначе
    нечем. Операция из закрытого периода не удаляется — 422.
    """
    record = await service.delete(spreadsheet_id, record_id)
    return DataResponse(data=RecordResponse.model_validate(record))
