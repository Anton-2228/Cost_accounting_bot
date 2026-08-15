"""Исключения сервиса и их отображение в HTTP-ответы.

`SyncError` — общий предок. Практический смысл имеет одно свойство —
:attr:`SyncError.terminal`: по нему движок решает, отчитаться ли в api обычной
неудачей (Google моргнул, поможет повтор) или терминальной (файл удалён, доступ
отозван — повтор получит тот же ответ, и пользователю нужно сказать сразу).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

#: Коды Google, означающие, что повторять бессмысленно, пока не вмешается
#: пользователь: доступ отозван (403), документ или лист удалён (404), запрос
#: ссылается на несуществующий диапазон (400).
TERMINAL_GOOGLE_STATUSES = frozenset({400, 401, 403, 404})


class SyncError(Exception):
    """Базовое исключение сервиса синхронизации."""

    #: Повтор заведомо получит тот же ответ.
    terminal: bool = False

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        self.message = message
        self.details = details
        super().__init__(message)


class GoogleApiError(SyncError):
    """Ошибка Google Sheets или Drive API после исчерпания повторов.

    Терминальность определяется кодом ответа, а не тем, сколько раз повтор уже
    провалился: «доступ отозван» не станет успешным ни на десятой попытке, ни
    на сотой.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        details: Any | None = None,
    ) -> None:
        self.status_code = status_code
        self.terminal = status_code in TERMINAL_GOOGLE_STATUSES
        super().__init__(message, details=details)


class ApiError(SyncError):
    """Ошибка вызова основного api (HTTP 4xx/5xx).

    Терминальной не считается никогда: api — часть системы, его недоступность
    чинится перезапуском, а не действиями пользователя.
    """

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"api {status_code}: {body}")


class SheetStructureError(SyncError):
    """Ответ Google не соответствует запросу: листов создано меньше, чем просили.

    Случай редкий — `batchUpdate` возвращает столько же `replies`, сколько было
    `requests`. Но молча обрезать `zip` нельзя: каждый потерянный ответ означает
    либо созданный и неучтённый лист, либо нарушенный порядок, а из этого
    родится соответствие «адресат → чужой лист», которое затем перезапишет
    чужие данные.
    """


async def _google_api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GoogleApiError)  # noqa: S101 — гарантировано регистрацией
    return JSONResponse(
        status_code=502,
        content={
            "code": "google_api_error",
            "message": exc.message,
            "details": {"status_code": exc.status_code, "terminal": exc.terminal},
        },
    )


async def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)  # noqa: S101
    body = exc.body if isinstance(exc.body, dict) else {"message": str(exc.body)}
    return JSONResponse(status_code=exc.status_code, content=body)


async def _sync_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SyncError)  # noqa: S101
    return JSONResponse(
        status_code=500,
        content={
            "code": "sync_error",
            "message": exc.message,
            "details": exc.details or {},
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Подключает обработчики исключений сервиса.

    Порядок важен: FastAPI выбирает обработчик по точному классу, а затем по
    предкам, поэтому частные регистрируются раньше общего.
    """
    app.add_exception_handler(GoogleApiError, _google_api_error_handler)
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(SyncError, _sync_error_handler)
