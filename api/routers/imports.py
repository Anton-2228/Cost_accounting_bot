"""Эндпоинты вчитывания правок листов в базу (служебные, для gsheets)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies.services import get_category_import_service, get_source_import_service
from api.requests.imports.import_rows_request import ImportRowsRequest
from api.responses.common.data_response import DataResponse
from api.responses.imports.sheet_import_result_response import SheetImportResultResponse
from api.services.category_import_service import CategoryImportService
from api.services.source_import_service import SourceImportService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}/import", tags=["service"])


@router.post("/categories", response_model=DataResponse[SheetImportResultResponse])
async def import_categories(
    spreadsheet_id: int,
    payload: ImportRowsRequest,
    service: CategoryImportService = Depends(get_category_import_service),
) -> DataResponse[SheetImportResultResponse]:
    """Применяет лист `Categories` целиком.

    Ответ 200 и с ошибкой разбора: ошибка не в запросе, а в содержимом листа
    пользователя. Она едет как **данные** (`error` с русским текстом) вместе с
    гарантией, что в БД не записано ничего.
    """
    result = await service.import_rows(spreadsheet_id, payload.rows)
    return DataResponse(data=SheetImportResultResponse.model_validate(result))


@router.post("/bills", response_model=DataResponse[SheetImportResultResponse])
async def import_bills(
    spreadsheet_id: int,
    payload: ImportRowsRequest,
    service: SourceImportService = Depends(get_source_import_service),
) -> DataResponse[SheetImportResultResponse]:
    """Применяет лист `Bills` целиком.

    Колонка `Current balance` не читается: баланс вычисляется из операций и
    переводов, и записывать его обратно значило бы закреплять расхождение.
    """
    result = await service.import_rows(spreadsheet_id, payload.rows)
    return DataResponse(data=SheetImportResultResponse.model_validate(result))
