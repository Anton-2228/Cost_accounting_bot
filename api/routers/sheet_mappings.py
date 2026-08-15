"""Эндпоинты соответствия «адресат → лист документа» (служебные, для gsheets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies.services import get_sheet_mapping_service
from api.requests.sheet_mappings.upsert_sheet_mapping_request import UpsertSheetMappingRequest
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.sheet_mappings.sheet_mapping_response import SheetMappingResponse
from api.services.sheet_mapping_service import SheetMappingService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}/sheet-mappings", tags=["service"])


@router.get("", response_model=ItemsResponse[SheetMappingResponse])
async def list_sheet_mappings(
    spreadsheet_id: int,
    service: SheetMappingService = Depends(get_sheet_mapping_service),
) -> ItemsResponse[SheetMappingResponse]:
    """Все известные листы документа.

    Это знание хранит api, а не `google_sheets_service`: у того нет своей базы, и
    после перезапуска он иначе не знал бы, создан ли уже лист периода.
    """
    mappings = await service.list_by_spreadsheet(spreadsheet_id)
    return ItemsResponse(items=[SheetMappingResponse.model_validate(item) for item in mappings])


@router.post("", response_model=DataResponse[SheetMappingResponse])
async def upsert_sheet_mapping(
    spreadsheet_id: int,
    payload: UpsertSheetMappingRequest,
    service: SheetMappingService = Depends(get_sheet_mapping_service),
) -> DataResponse[SheetMappingResponse]:
    """Запоминает созданный лист. Повторный вызов обновляет запись."""
    mapping = await service.upsert(
        spreadsheet_id,
        target=payload.target,
        google_sheet_id=payload.google_sheet_id,
        title=payload.title,
        period_id=payload.period_id,
    )
    return DataResponse(data=SheetMappingResponse.model_validate(mapping))
