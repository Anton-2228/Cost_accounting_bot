"""Регистрация обработчиков исключений: единый формат ответа об ошибке."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from api.exceptions.base import AppException
from api.responses.common.error_response import ErrorResponse

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: object | None = None,
) -> JSONResponse:
    payload = ErrorResponse(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload))


def register_exception_handlers(app: FastAPI) -> None:
    """Регистрирует обработчики доменных и инфраструктурных исключений."""

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "Некорректный запрос",
            details=exc.errors(),
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        # Страховка за уникальными ключами: занятый псевдоним, повторный /start,
        # тип товара, уже закреплённый за другой категорией.
        logger.warning("Нарушено ограничение целостности: %s", exc)
        return _error_response(
            status.HTTP_409_CONFLICT,
            "conflict",
            "Нарушено ограничение целостности данных",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Необработанная ошибка: %s", exc)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Внутренняя ошибка сервиса",
        )
