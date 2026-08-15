"""Эндпоинты переводов между счетами."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.dependencies.services import get_transfer_service
from api.requests.transfers.create_transfer_request import CreateTransferRequest
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.transfers.transfer_response import TransferResponse
from api.services.transfer_service import TransferService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}/transfers", tags=["transfers"])


@router.get("", response_model=ItemsResponse[TransferResponse])
async def list_transfers(
    spreadsheet_id: int,
    period_id: int | None = None,
    service: TransferService = Depends(get_transfer_service),
) -> ItemsResponse[TransferResponse]:
    """Переводы периода; без `period_id` — текущего."""
    transfers = await service.list_by_period(spreadsheet_id, period_id)
    return ItemsResponse(items=[TransferResponse.model_validate(item) for item in transfers])


@router.post(
    "",
    response_model=DataResponse[TransferResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_transfer(
    spreadsheet_id: int,
    payload: CreateTransferRequest,
    service: TransferService = Depends(get_transfer_service),
) -> DataResponse[TransferResponse]:
    """Переводит сумму между счетами одной строкой.

    Обе стороны перевода — одна запись, а не два движения баланса: потерять
    половину перевода при сбое теперь физически нечем. В доходы и расходы
    перевод не попадает.
    """
    transfer = await service.create(
        spreadsheet_id,
        from_source_id=payload.from_source_id,
        to_source_id=payload.to_source_id,
        amount=payload.amount,
        notes=payload.notes,
    )
    return DataResponse(data=TransferResponse.model_validate(transfer))


@router.delete("/last", response_model=DataResponse[TransferResponse])
async def delete_last_transfer(
    spreadsheet_id: int,
    service: TransferService = Depends(get_transfer_service),
) -> DataResponse[TransferResponse]:
    """Удаляет последний перевод текущего периода.

    Объявлен до `/{transfer_id}`: иначе литерал `last` попал бы в параметр пути.
    """
    transfer = await service.delete(spreadsheet_id)
    return DataResponse(data=TransferResponse.model_validate(transfer))


@router.delete("/{transfer_id}", response_model=DataResponse[TransferResponse])
async def delete_transfer(
    spreadsheet_id: int,
    transfer_id: int,
    service: TransferService = Depends(get_transfer_service),
) -> DataResponse[TransferResponse]:
    """Удаляет перевод по идентификатору."""
    transfer = await service.delete(spreadsheet_id, transfer_id)
    return DataResponse(data=TransferResponse.model_validate(transfer))
