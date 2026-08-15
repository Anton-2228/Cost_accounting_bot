"""Эндпоинты учётной таблицы: создание, доступы, справочники, удаление."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.dependencies.services import get_spreadsheet_service
from api.requests.spreadsheets.add_access_request import AddAccessRequest
from api.requests.spreadsheets.create_spreadsheet_request import CreateSpreadsheetRequest
from api.requests.spreadsheets.set_google_id_request import SetGoogleIdRequest
from api.responses.categories.category_response import CategoryResponse
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.sources.source_balance_response import SourceBalanceResponse
from api.responses.sources.source_response import SourceResponse
from api.responses.spreadsheets.spreadsheet_access_response import SpreadsheetAccessResponse
from api.responses.spreadsheets.spreadsheet_response import SpreadsheetResponse
from api.services.spreadsheet_service import SpreadsheetService

router = APIRouter(prefix="/spreadsheets", tags=["spreadsheets"])


@router.post(
    "",
    response_model=DataResponse[SpreadsheetResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_spreadsheet(
    payload: CreateSpreadsheetRequest,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> DataResponse[SpreadsheetResponse]:
    """Создаёт учётную таблицу пользователя (команда `/start`).

    Google-документа в ответе ещё нет: api в Google не ходит, а ставит задачу
    `STRUCTURE`. Повторный вызов для того же пользователя — 409.
    """
    spreadsheet = await service.create(
        telegram_id=payload.telegram_id,
        title=payload.title,
        reset_day=payload.reset_day,
        timezone=payload.timezone,
        email=payload.email,
    )
    return DataResponse(data=SpreadsheetResponse.model_validate(spreadsheet))


@router.get(
    "/by-telegram/{telegram_id}",
    response_model=DataResponse[SpreadsheetResponse],
)
async def get_spreadsheet_by_telegram_id(
    telegram_id: int,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> DataResponse[SpreadsheetResponse]:
    """Таблица пользователя телеграма.

    Объявлен до `/{spreadsheet_id}`, иначе литерал `by-telegram` был бы разобран
    как идентификатор и превратился в 422.

    Готовность документа не проверяется намеренно: именно этим запросом бот и
    узнаёт, появился ли уже `google_spreadsheet_id`.
    """
    spreadsheet = await service.get_by_telegram_id(telegram_id)
    return DataResponse(data=SpreadsheetResponse.model_validate(spreadsheet))


@router.get("/{spreadsheet_id}", response_model=DataResponse[SpreadsheetResponse])
async def get_spreadsheet(
    spreadsheet_id: int,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> DataResponse[SpreadsheetResponse]:
    """Таблица по идентификатору."""
    spreadsheet = await service.get(spreadsheet_id)
    return DataResponse(data=SpreadsheetResponse.model_validate(spreadsheet))


@router.delete("/{spreadsheet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_spreadsheet(
    spreadsheet_id: int,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> None:
    """Удаляет таблицу вместе с пользователем и всем содержимым.

    Google-документ остаётся у пользователя: он его архив, и удалять его молча
    система права не имеет.
    """
    await service.delete(spreadsheet_id)


@router.get(
    "/{spreadsheet_id}/categories",
    response_model=ItemsResponse[CategoryResponse],
)
async def list_categories(
    spreadsheet_id: int,
    only_active: bool = False,
    include_deleted: bool = False,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> ItemsResponse[CategoryResponse]:
    """Категории документа.

    `only_active=true` — только те, что участвуют в подсказках бота.
    `include_deleted=true` — вместе с удалёнными; нужно перерисовке архивных
    листов, где операции ссылаются на категории, которых уже нет.
    """
    categories = await service.list_categories(
        spreadsheet_id,
        only_active=only_active,
        include_deleted=include_deleted,
    )
    return ItemsResponse(items=[CategoryResponse.model_validate(item) for item in categories])


@router.get("/{spreadsheet_id}/sources", response_model=ItemsResponse[SourceResponse])
async def list_sources(
    spreadsheet_id: int,
    only_active: bool = False,
    include_deleted: bool = False,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> ItemsResponse[SourceResponse]:
    """Счета документа. Параметры — как у категорий."""
    sources = await service.list_sources(
        spreadsheet_id,
        only_active=only_active,
        include_deleted=include_deleted,
    )
    return ItemsResponse(items=[SourceResponse.model_validate(item) for item in sources])


@router.get(
    "/{spreadsheet_id}/balances",
    response_model=ItemsResponse[SourceBalanceResponse],
)
async def list_balances(
    spreadsheet_id: int,
    only_active: bool = False,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> ItemsResponse[SourceBalanceResponse]:
    """Текущие балансы счетов.

    Баланс не хранится, а считается из начального остатка, операций и переводов:
    потерянная правка не может разойтись с реестром навсегда, как это было с
    колонкой `current_balance`.
    """
    balances = await service.list_balances(spreadsheet_id, only_active=only_active)
    return ItemsResponse(items=[SourceBalanceResponse.model_validate(item) for item in balances])


@router.get(
    "/{spreadsheet_id}/accesses",
    response_model=ItemsResponse[SpreadsheetAccessResponse],
)
async def list_accesses(
    spreadsheet_id: int,
    pending_only: bool = False,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> ItemsResponse[SpreadsheetAccessResponse]:
    """Доступы к документу. `pending_only=true` — только те, что предстоит выдать."""
    accesses = (
        await service.list_pending_accesses(spreadsheet_id)
        if pending_only
        else await service.list_accesses(spreadsheet_id)
    )
    return ItemsResponse(
        items=[SpreadsheetAccessResponse.model_validate(item) for item in accesses]
    )


@router.post(
    "/{spreadsheet_id}/accesses",
    response_model=DataResponse[SpreadsheetAccessResponse],
    status_code=status.HTTP_201_CREATED,
)
async def add_access(
    spreadsheet_id: int,
    payload: AddAccessRequest,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> DataResponse[SpreadsheetAccessResponse]:
    """Добавляет почту с доступом и просит gsheets его выдать."""
    access = await service.add_access(spreadsheet_id, payload.email, payload.role)
    return DataResponse(data=SpreadsheetAccessResponse.model_validate(access))


@router.post("/{spreadsheet_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def request_import(
    spreadsheet_id: int,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> None:
    """Просит вчитать правки листов `Categories` и `Bills` (команда `/sync`).

    Ответ 202, а не 200: работа только поставлена в очередь. Результат приедет
    асинхронно — ошибка разбора попадёт в уведомления.
    """
    await service.request_import(spreadsheet_id)


@router.post(
    "/{spreadsheet_id}/google-id",
    response_model=DataResponse[SpreadsheetResponse],
    tags=["service"],
)
async def set_google_id(
    spreadsheet_id: int,
    payload: SetGoogleIdRequest,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> DataResponse[SpreadsheetResponse]:
    """Привязывает созданный Google-документ (служебное, для gsheets).

    Идемпотентно для того же самого идентификатора: сервис мог создать документ и
    потерять ответ. Попытка привязать другой документ — 409.
    """
    spreadsheet = await service.set_google_id(spreadsheet_id, payload.google_spreadsheet_id)
    return DataResponse(data=SpreadsheetResponse.model_validate(spreadsheet))


@router.post(
    "/{spreadsheet_id}/accesses/{access_id}/granted",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["service"],
)
async def mark_access_granted(
    spreadsheet_id: int,
    access_id: int,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> None:
    """Отмечает доступ выданным (служебное, для gsheets)."""
    await service.mark_access_granted(spreadsheet_id, access_id)


@router.post(
    "/{spreadsheet_id}/accesses/{access_id}/failed",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["service"],
)
async def mark_access_failed(
    spreadsheet_id: int,
    access_id: int,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> None:
    """Google отказался выдать доступ на эту почту (служебное, для gsheets).

    Запись удаляется и пользователь получает уведомление. Отдельный эндпоинт
    нужен потому, что решение принимает gsheets (он видит ответ Google), а
    русский текст живёт в api.
    """
    await service.mark_access_failed(spreadsheet_id, access_id)
