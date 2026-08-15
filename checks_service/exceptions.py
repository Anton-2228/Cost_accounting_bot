"""Исключения сервиса и их отображение в HTTP-ответы.

Каждое исключение несёт машинный `code`, по которому Mini App выбирает русский
текст плашки. Текст здесь тоже русский — страница показывает его, если код ей
незнаком, но опирается именно на код: сообщение можно переписать, не трогая JS.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ChecksError(Exception):
    """Базовое исключение сервиса добавления чеков."""

    status_code: int = 500
    code: str = "checks_error"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        self.message = message
        self.details = details
        super().__init__(message)


class UnauthorizedError(ChecksError):
    """Подпись `initData` не сошлась, протухла или её вовсе нет."""

    status_code = 401
    code = "unauthorized"


class ForbiddenError(ChecksError):
    """Подпись верна, но этому telegram_id пользоваться сервисом нельзя."""

    status_code = 403
    code = "forbidden"


class FormatNotSupportedError(ChecksError):
    """Ни один парсер не узнал QR-строку.

    Ожидаемый случай, а не сбой: пользователь мог отсканировать штрихкод
    товара, ссылку или чек страны, которую мы ещё не поддерживаем.
    """

    status_code = 422
    code = "format_not_supported"


class ReceiptFetchError(ChecksError):
    """Внешний сервис расшифровки не отдал чек.

    В БД при этом не пишется ничего: чек в базе всегда полный. Иначе к разбору
    пришлось бы прикручивать фоновый дозабор и обработку получекoв.
    """

    status_code = 502
    code = "receipt_fetch_failed"


class ReceiptNotFoundError(ReceiptFetchError):
    """Внешний сервис ответил, что такого чека нет.

    Отделено от общего сбоя намеренно: повтор даст тот же ответ, и предлагать
    «попробуйте ещё раз» здесь значит врать.
    """

    status_code = 404
    code = "receipt_not_found"


class SpreadsheetNotFoundError(ChecksError):
    """У пользователя ещё нет учётной таблицы — чек некуда класть."""

    status_code = 404
    code = "spreadsheet_not_found"


class CheckAlreadySavedError(ChecksError):
    """Этот чек в документе уже есть."""

    status_code = 409
    code = "check_already_saved"


class ApiError(ChecksError):
    """Основное api ответило неожиданным статусом.

    Своего кода не выдумывает: наружу уезжает 502, потому что для Mini App это
    именно недоступность внутренней части системы, а не ошибка пользователя.
    """

    status_code = 502
    code = "api_error"

    def __init__(self, status_code: int, body: Any) -> None:
        self.api_status_code = status_code
        self.body = body
        super().__init__(f"api {status_code}: {body}", details={"status_code": status_code})


async def _checks_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ChecksError)  # noqa: S101 — гарантировано регистрацией
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Подключает единый обработчик исключений сервиса.

    Обработчик один на всю иерархию: он читает `status_code` и `code` с самого
    исключения, поэтому новый подкласс не требует ни новой функции, ни правки
    регистрации — и не может по забывчивости уехать наружу пятисоткой.
    """
    app.add_exception_handler(ChecksError, _checks_error_handler)
