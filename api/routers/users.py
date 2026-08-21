"""Эндпоинты, отвечающие про пользователя целиком, а не про один документ."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.dependencies.services import get_spreadsheet_service
from api.responses.common.items_response import ItemsResponse
from api.responses.spreadsheets.spreadsheet_response import SpreadsheetResponse
from api.services.spreadsheet_service import SpreadsheetService

router = APIRouter(prefix="/users/{telegram_id}", tags=["users"])


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
