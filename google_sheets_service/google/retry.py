"""Повторы вызовов Google API."""

from __future__ import annotations

import asyncio
import random
import ssl
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

from google_sheets_service.exceptions import GoogleApiError
from google_sheets_service.logging import get_logger

logger = get_logger(__name__)

#: Коды, после которых повтор осмыслен: перегрузка квоты и сбои на стороне
#: Google. Всё остальное (403, 404, 400) повтор не починит — такие ошибки
#: становятся терминальными в :class:`GoogleApiError` и едут в api как есть.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

#: Транзиентные сетевые сбои: таймаут чтения сокета, обрыв соединения, ошибки
#: ssl и httplib2. Повторять их надо так же, как 5xx, но синхронный SDK бросает
#: их **мимо** `HttpError` — без этой ветки они проходят все `except` движка и
#: роняют весь тик. `TimeoutError` и `ConnectionError` — подклассы `OSError`.
TRANSIENT_ERRORS = (
    TimeoutError,
    ConnectionError,
    ssl.SSLError,
    httplib2.HttpLib2Error,
)


class RetryPolicy:
    """Экспоненциальные повторы для асинхронных обёрток над Google API.

    Применяется как декоратор: клиент оборачивает в неё свои методы прямо в
    `__init__`, поэтому один экземпляр политики обслуживает весь клиент и
    настройки задаются в одном месте.
    """

    def __init__(
        self,
        *,
        max_retries: int = 5,
        base_seconds: float = 1.0,
        jitter_seconds: float = 0.3,
    ) -> None:
        self._max_retries = max_retries
        self._base = base_seconds
        self._jitter = jitter_seconds

    def __call__[**P, R](self, func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        """Оборачивает корутину повторами."""

        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await self._run(func, *args, **kwargs)

        return wrapper

    async def _run[**P, R](
        self,
        func: Callable[P, Awaitable[R]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> R:
        """Выполняет вызов, повторяя его на восстановимых ошибках."""
        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            try:
                return await func(*args, **kwargs)
            except HttpError as exc:
                last_error = exc
                status = self._http_status(exc)
                if status not in RETRY_STATUSES or attempt == self._max_retries:
                    raise GoogleApiError(
                        f"Google API ответил {status}: {_reason(exc)}",
                        status_code=status,
                    ) from exc
                await self._backoff(attempt, f"Google API {status}")
                attempt += 1
            except TRANSIENT_ERRORS as exc:
                last_error = exc
                if attempt == self._max_retries:
                    raise GoogleApiError(
                        f"Сетевая ошибка Google API после повторов: {exc}"
                    ) from exc
                await self._backoff(attempt, f"сетевая ошибка ({exc})")
                attempt += 1
        # Недостижимо: любая ветка выше либо возвращает, либо бросает. Но без
        # этой строки mypy не видит, что функция всегда завершается значением.
        raise GoogleApiError(f"Повторы исчерпаны: {last_error}")

    async def _backoff(self, attempt: int, reason: str) -> None:
        """Ждёт перед следующей попыткой: экспонента плюс джиттер.

        Джиттер обязателен: без него несколько задач, упавших на одной и той же
        квоте, проснутся одновременно и упрутся в неё снова.
        """
        delay = self._base * (2**attempt) + random.uniform(0, self._jitter)  # noqa: S311
        logger.warning(
            "%s, повтор %s/%s через %.2f с", reason, attempt + 1, self._max_retries, delay
        )
        await asyncio.sleep(delay)

    @staticmethod
    def _http_status(exc: HttpError) -> int | None:
        """Достаёт код ответа из `HttpError`; None, если не получилось."""
        try:
            return int(exc.resp.status)
        except (AttributeError, ValueError, TypeError):
            return None


def _reason(exc: HttpError) -> str:
    """Короткое объяснение отказа из тела ответа Google.

    Полный `str(HttpError)` содержит URI запроса с параметрами и занимает
    несколько строк. Это сообщение едет пользователю в уведомлении, поэтому от
    него нужна причина, а не дамп запроса.
    """
    try:
        return str(exc.error_details or exc.reason or exc)
    except (AttributeError, ValueError):
        return str(exc)


def to_dict(value: Any) -> dict[str, Any]:
    """Гарантирует, что ответ Google — словарь, а не None."""
    return value if isinstance(value, dict) else {}
