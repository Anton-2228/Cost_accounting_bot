"""Эндпоинты учётных периодов и статистики."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies.services import get_period_service
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.periods.category_daily_total_response import CategoryDailyTotalResponse
from api.responses.periods.period_response import PeriodResponse
from api.services.period_service import PeriodService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}/periods", tags=["periods"])


@router.get("", response_model=ItemsResponse[PeriodResponse])
async def list_periods(
    spreadsheet_id: int,
    service: PeriodService = Depends(get_period_service),
) -> ItemsResponse[PeriodResponse]:
    """Все периоды документа по возрастанию даты начала."""
    periods = await service.list_all(spreadsheet_id)
    return ItemsResponse(items=[PeriodResponse.model_validate(item) for item in periods])


@router.get("/current", response_model=DataResponse[PeriodResponse])
async def get_current_period(
    spreadsheet_id: int,
    service: PeriodService = Depends(get_period_service),
) -> DataResponse[PeriodResponse]:
    """Период, которому принадлежит сегодняшний день документа.

    Объявлен до `/{period_id}`-маршрутов. Период здесь не создаётся: чтение не
    должно менять данные — этим занимаются операция и ролловер.
    """
    period = await service.current(spreadsheet_id)
    return DataResponse(data=PeriodResponse.model_validate(period))


@router.get(
    "/{period_id}/statistics",
    response_model=ItemsResponse[CategoryDailyTotalResponse],
)
async def get_period_statistics(
    spreadsheet_id: int,
    period_id: int,
    service: PeriodService = Depends(get_period_service),
) -> ItemsResponse[CategoryDailyTotalResponse]:
    """Дневные итоги по категориям за период — основа листа статистики."""
    totals = await service.daily_totals(spreadsheet_id, period_id)
    return ItemsResponse(
        items=[CategoryDailyTotalResponse.model_validate(item) for item in totals]
    )
