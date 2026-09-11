"""Эндпоинты, отвечающие про пользователя целиком, а не про один документ."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies.services import get_spreadsheet_service, get_user_service
from api.requests.users.set_language_request import SetLanguageRequest
from api.responses.common.data_response import DataResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.spreadsheets.spreadsheet_response import SpreadsheetResponse
from api.responses.users.user_response import UserResponse
from api.services.spreadsheet_service import SpreadsheetService
from api.services.user_service import UserService

router = APIRouter(prefix="/users/{telegram_id}", tags=["users"])


@router.get("", response_model=DataResponse[UserResponse])
async def get_user(
    telegram_id: int,
    service: UserService = Depends(get_user_service),
) -> DataResponse[UserResponse]:
    """Пользователь и его язык; 404 по ресурсу `user`, если его нет.

    Незнакомому пользователю api языка не выдумывает: умолчание — дело того,
    кто спрашивает (бот и Mini App говорят с ним по-английски).
    """
    user = await service.get(telegram_id)
    return DataResponse(data=UserResponse.model_validate(user))


@router.put("/language", response_model=DataResponse[UserResponse])
async def set_user_language(
    telegram_id: int,
    body: SetLanguageRequest,
    service: UserService = Depends(get_user_service),
) -> DataResponse[UserResponse]:
    """Записывает язык пользователя, заводя его, если он ещё не известен.

    `PUT`, а не `PATCH`: язык — единственное, что здесь пишется, и повтор того
    же запроса ничего не меняет. Незнакомый пользователь — не 404: язык
    выбирается на `/start` раньше, чем появится таблица, а вместе с ней до сих
    пор появлялся и пользователь.
    """
    user = await service.set_language(telegram_id, body.language)
    return DataResponse(data=UserResponse.model_validate(user))


@router.get("/spreadsheets", response_model=ItemsResponse[SpreadsheetResponse])
async def list_user_spreadsheets(
    telegram_id: int,
    service: SpreadsheetService = Depends(get_spreadsheet_service),
) -> ItemsResponse[SpreadsheetResponse]:
    """Все документы пользователя за всё время, включая отвязанные.

    Отдельный маршрут, а не флаг у `/spreadsheets/by-telegram/{telegram_id}`:
    тот отвечает на вопрос «с каким документом работать сейчас» и обязан
    оставаться единственным, иначе бот однажды получит по нему отвязанный.

    Отвязанные документы здесь не помеха, а цель: деньги, ушедшие на модель,
    потрачены независимо от того, ведёт ли пользователь учёт до сих пор.
    Отличить их можно по `deleted_at`.
    """
    spreadsheets = await service.list_by_telegram_id(telegram_id)
    return ItemsResponse(
        items=[SpreadsheetResponse.model_validate(item) for item in spreadsheets]
    )
