"""Исключения сервиса и их отображение в HTTP-ответы.

Каждое исключение несёт машинный `code`, по которому Mini App выбирает текст
плашки на языке пользователя. `message` — для журнала: он на одном языке для
всех, и страница его не показывает никогда — незнакомый код получает у неё
общую фразу на языке пользователя.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from checks_service.logging import get_logger

logger = get_logger(__name__)


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
    # Пишем отказ здесь, а не на каждом `raise`. Причина не в удобстве: Mini App
    # выбирает текст плашки по коду, поэтому все девять способов не расшифровать
    # чек читаются пользователем одинаково — «сервис недоступен», — а больше
    # половины мест бросали исключение молча. На своей машине это незаметно, на
    # чужой означает отказ вообще без следа в логах. Единая точка гарантирует
    # строку любому отказу, включая те, которые появятся позже.
    #
    # Пятисотые едут с цепочкой исключений: настоящая причина (ошибка `httpx`,
    # тело чужого ответа) лежит в `__cause__`, и без неё в логе остаётся наша
    # формулировка, по которой ничего не чинится. Клиентские отказы — сценарий,
    # а не сбой, и уровня `info` им хватает.
    if exc.status_code >= 500:  # noqa: PLR2004 — граница «сбой/сценарий»
        logger.error(
            "Отказ %s (%s): %s; детали: %s",
            exc.code,
            exc.status_code,
            exc.message,
            exc.details,
            exc_info=exc,
        )
    else:
        logger.info(
            "Отказ %s (%s): %s; детали: %s",
            exc.code,
            exc.status_code,
            exc.message,
            exc.details,
        )
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
