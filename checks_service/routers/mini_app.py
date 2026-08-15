"""Эндпоинты Mini App: распознать чек и добавить его."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from checks_service.auth.dependencies import current_telegram_id
from checks_service.requests.scan_request import ScanRequest
from checks_service.responses.check_preview_response import CheckPreviewResponse
from checks_service.responses.saved_check_response import SavedCheckResponse
from checks_service.services.check_intake import CheckIntakeService

router = APIRouter(prefix="/api/v1/mini-app", tags=["mini-app"])


def get_intake(request: Request) -> CheckIntakeService:
    """Достаёт сервис приёма чеков из состояния приложения."""
    intake = getattr(request.app.state, "intake", None)
    if intake is None:  # pragma: no cover — возможно только при сбое сборки
        raise RuntimeError("Сервис приёма чеков не инициализирован в app.state")
    return intake


@router.post("/checks/preview", response_model=CheckPreviewResponse)
async def preview_check(
    payload: ScanRequest,
    telegram_id: int = Depends(current_telegram_id),
    intake: CheckIntakeService = Depends(get_intake),
) -> CheckPreviewResponse:
    """Распознаёт формат чека и собирает плашку.

    Внешний сервис расшифровки не зовётся: он платный и лимитированный, а
    пользователь ещё не подтвердил, что чек нужно добавлять. Распознавание —
    на сервере, поэтому страница не знает ни одного формата, и следующий
    формат появится без единой правки JS.
    """
    return CheckPreviewResponse.of(await intake.preview(payload.qr_raw, telegram_id=telegram_id))


@router.post(
    "/checks",
    response_model=SavedCheckResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_check(
    payload: ScanRequest,
    telegram_id: int = Depends(current_telegram_id),
    intake: CheckIntakeService = Depends(get_intake),
) -> SavedCheckResponse:
    """Расшифровывает чек и сохраняет его целиком.

    Отказ внешнего сервиса означает, что в БД не появится ничего: чек там
    всегда полный, и «дозаберём потом» не бывает.
    """
    return SavedCheckResponse.of(await intake.save(payload.qr_raw, telegram_id=telegram_id))
