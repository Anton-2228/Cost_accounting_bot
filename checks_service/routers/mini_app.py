"""Эндпоинты Mini App: язык пользователя, распознать чек, добавить или отложить его."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from checks_service import constants
from checks_service.auth.dependencies import current_telegram_id
from checks_service.main_api import ApiGateway
from checks_service.requests.scan_request import ScanRequest
from checks_service.responses.check_preview_response import CheckPreviewResponse
from checks_service.responses.me_response import MeResponse
from checks_service.responses.pending_check_response import (
    PendingCheckResponse,
    PendingChecksResponse,
)
from checks_service.responses.saved_check_response import SavedCheckResponse
from checks_service.services.check_intake import CheckIntakeService, Deferred

router = APIRouter(prefix="/api/v1/mini-app", tags=["mini-app"])


def get_intake(request: Request) -> CheckIntakeService:
    """Достаёт сервис приёма чеков из состояния приложения."""
    intake = getattr(request.app.state, "intake", None)
    if intake is None:  # pragma: no cover — возможно только при сбое сборки
        raise RuntimeError("Сервис приёма чеков не инициализирован в app.state")
    return intake


def get_api(request: Request) -> ApiGateway:
    """Достаёт шлюз к основному api из состояния приложения."""
    api = getattr(request.app.state, "api", None)
    if api is None:  # pragma: no cover — возможно только при сбое сборки
        raise RuntimeError("Шлюз к api не инициализирован в app.state")
    return api


@router.get("/me", response_model=MeResponse)
async def me(
    telegram_id: int = Depends(current_telegram_id),
    api: ApiGateway = Depends(get_api),
) -> MeResponse:
    """Кто открыл Mini App и на каком языке с ним говорить.

    Страница спрашивает об этом до того, как открыть сканер: язык выбирается в
    боте и хранится в api, а своего способа его узнать у страницы нет — язык
    клиента Telegram может не совпадать с выбранным. Незнакомый api
    пользователь говорит по-английски: так с ним говорит и бот.
    """
    language = await api.users.language(telegram_id)
    return MeResponse(telegram_id=telegram_id, language=language or constants.DEFAULT_LANGUAGE)


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
    response_model=SavedCheckResponse | PendingCheckResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_202_ACCEPTED: {"model": PendingCheckResponse}},
)
async def add_check(
    payload: ScanRequest,
    response: Response,
    telegram_id: int = Depends(current_telegram_id),
    intake: CheckIntakeService = Depends(get_intake),
) -> SavedCheckResponse | PendingCheckResponse:
    """Расшифровывает чек и сохраняет его целиком — или откладывает.

    201 — чек добавлен. 202 — внешний сервис его пока не отдал, но это
    проходит само (касса ещё не передала чек в налоговую): чек отложен, фон
    будет спрашивать о нём сам, а в Mini App он виден в списке отложенных. Прочие
    отказы внешнего сервиса — ошибка, и в БД не появляется ничего.
    """
    result = await intake.save(payload.qr_raw, telegram_id=telegram_id)
    if isinstance(result, Deferred):
        response.status_code = status.HTTP_202_ACCEPTED
        return PendingCheckResponse.of(result.pending, result.parsed.preview)
    return SavedCheckResponse.of(result)


@router.get("/pending-checks", response_model=PendingChecksResponse)
async def list_pending_checks(
    telegram_id: int = Depends(current_telegram_id),
    intake: CheckIntakeService = Depends(get_intake),
) -> PendingChecksResponse:
    """Отложенные чеки пользователя — их страница показывает при открытии.

    Истёкшие (фон сдался) тоже здесь: их можно повторить вручную или удалить.
    """
    views = await intake.list_pending(telegram_id=telegram_id)
    return PendingChecksResponse(
        items=[PendingCheckResponse.of(view.pending, view.preview) for view in views]
    )


@router.post(
    "/pending-checks/{pending_id}/retry",
    response_model=SavedCheckResponse,
    status_code=status.HTTP_201_CREATED,
)
async def retry_pending_check(
    pending_id: int,
    telegram_id: int = Depends(current_telegram_id),
    intake: CheckIntakeService = Depends(get_intake),
) -> SavedCheckResponse:
    """Повторяет запрос отложенного чека прямо сейчас.

    Неудача отвечает тем же отказом, что и скан (`receipt_not_ready`, …), а чек
    остаётся в списке. Пока чек спрашивает фон — 409 `pending_check_busy`.
    """
    return SavedCheckResponse.of(await intake.retry(pending_id, telegram_id=telegram_id))


@router.delete("/pending-checks/{pending_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pending_check(
    pending_id: int,
    telegram_id: int = Depends(current_telegram_id),
    intake: CheckIntakeService = Depends(get_intake),
) -> None:
    """Убирает отложенный чек: фон о нём больше не спрашивает."""
    await intake.delete_pending(pending_id, telegram_id=telegram_id)
