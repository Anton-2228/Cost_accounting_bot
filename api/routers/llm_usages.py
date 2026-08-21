"""Эндпоинт учёта обращений к модели."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.dependencies.services import get_llm_usage_service
from api.requests.llm_usages.record_llm_usage_request import RecordLlmUsageRequest
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.llm_usages.llm_usage_response import LlmUsageResponse
from api.services.llm_usage_service import LlmUsageService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}", tags=["llm-usages"])


@router.post(
    "/llm-usages",
    response_model=DataResponse[LlmUsageResponse],
    status_code=status.HTTP_201_CREATED,
)
async def record_llm_usage(
    spreadsheet_id: int,
    payload: RecordLlmUsageRequest,
    service: LlmUsageService = Depends(get_llm_usage_service),
) -> DataResponse[LlmUsageResponse]:
    """Записывает, во что обошлось одно обращение к модели.

    Замер приезжает от того, кто звал модель: ключ провайдера есть только у него,
    и api по-прежнему не делает ни одного внешнего вызова. Пишутся лишь
    состоявшиеся вызовы — то, за что провайдер выставил счёт.
    """
    usage = await service.record(
        spreadsheet_id,
        operation=payload.operation,
        entity_kind=payload.entity_kind,
        entity_id=payload.entity_id,
        model=payload.model,
        prompt_tokens=payload.prompt_tokens,
        completion_tokens=payload.completion_tokens,
        total_tokens=payload.total_tokens,
        cost=payload.cost,
        raw_usage=payload.raw_usage,
    )
    return DataResponse(data=LlmUsageResponse.model_validate(usage))


@router.get("/llm-usages", response_model=ItemsResponse[LlmUsageResponse])
async def list_llm_usages(
    spreadsheet_id: int,
    service: LlmUsageService = Depends(get_llm_usage_service),
) -> ItemsResponse[LlmUsageResponse]:
    """Все замеры документа в хронологическом порядке.

    Отдаются сами замеры, а не сумма: траты показываются разложенными по учётным
    периодам, а границы периода — это даты в часовом поясе документа. Считать их
    здесь значило бы завести в этой таблице вторую копию календарной логики,
    которая уже живёт в `periods`.

    Отвязанный документ читается наравне с живым: расход на модель не отменяется
    тем, что учёт по документу больше не ведут.
    """
    usages = await service.list_for_spreadsheet(spreadsheet_id)
    return ItemsResponse(items=[LlmUsageResponse.model_validate(item) for item in usages])
