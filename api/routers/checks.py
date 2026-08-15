"""Эндпоинты чеков: сохранение сырья, кэш типов, запись разобранного чека."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.dependencies.services import get_check_service
from api.domain.check_item import CheckItem, ProductTypeAssignment
from api.requests.checks.commit_check_request import CommitCheckRequest
from api.requests.checks.save_check_request import SaveCheckRequest
from api.responses.checks.cashed_record_response import CashedRecordResponse
from api.responses.checks.check_response import CheckResponse
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.records.record_response import RecordResponse
from api.services.check_service import CheckService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}", tags=["checks"])


@router.get("/checks", response_model=ItemsResponse[CheckResponse])
async def list_checks(
    spreadsheet_id: int,
    service: CheckService = Depends(get_check_service),
) -> ItemsResponse[CheckResponse]:
    """Сохранённые чеки документа в порядке поступления."""
    items = await service.list_checks(spreadsheet_id)
    return ItemsResponse(items=[CheckResponse.model_validate(item) for item in items])


@router.post(
    "/checks",
    response_model=DataResponse[CheckResponse],
    status_code=status.HTTP_201_CREATED,
)
async def save_check(
    spreadsheet_id: int,
    payload: SaveCheckRequest,
    service: CheckService = Depends(get_check_service),
) -> DataResponse[CheckResponse]:
    """Сохраняет расшифрованный чек. Повторный скан того же чека — 409.

    Сюда чек приезжает уже с расшифровкой: за QR-кодом во внешний сервис ходит
    `checks_service`, а api по-прежнему не делает ни одного внешнего вызова.
    """
    check = await service.save(
        spreadsheet_id,
        kind=payload.kind,
        qr_raw=payload.qr_raw,
        external_key=payload.external_key,
        raw_payload=payload.raw_payload,
        fetched_at=payload.fetched_at,
    )
    return DataResponse(data=CheckResponse.model_validate(check))


@router.get("/cashed-records", response_model=ItemsResponse[CashedRecordResponse])
async def list_cashed_records(
    spreadsheet_id: int,
    service: CheckService = Depends(get_check_service),
) -> ItemsResponse[CashedRecordResponse]:
    """Выученные соответствия «товар → тип».

    Разбор чека берёт их, чтобы не спрашивать модель о товарах, которые уже
    встречались.
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

    Стадии диалога, модель и подтверждения пользователя остаются у клиента: они
    перемежаются вопросами и живут в его состоянии. Сюда приезжает готовый
    результат — новые типы товаров, кэш и N операций, и ни одна часть не может
    уцелеть без остальных.
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
        check_json=payload.check_json,
    )
    return ItemsResponse(items=[RecordResponse.model_validate(item) for item in records])
