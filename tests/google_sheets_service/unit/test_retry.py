"""Повторы вызовов Google API."""

from __future__ import annotations

import ssl

import httplib2
import pytest
from googleapiclient.errors import HttpError

from google_sheets_service.exceptions import GoogleApiError
from google_sheets_service.google.retry import RetryPolicy


class _Response:
    """Минимальный ответ, какой ожидает `HttpError`."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "test"


def _http_error(status: int) -> HttpError:
    """Ошибка Google с указанным кодом."""
    return HttpError(_Response(status), b'{"error": {"message": "test"}}')


@pytest.fixture
def policy() -> RetryPolicy:
    """Политика без пауз: экспонента здесь только удлиняла бы прогон."""
    return RetryPolicy(max_retries=2, base_seconds=0, jitter_seconds=0)


async def test_successful_call_is_not_retried(policy: RetryPolicy) -> None:
    """Удачный вызов выполняется один раз."""
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    assert await policy(call)() == "ok"
    assert calls == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_transient_status_is_retried(policy: RetryPolicy, status: int) -> None:
    """Перегрузка квоты и сбои Google повторяются."""
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _http_error(status)
        return "ok"

    assert await policy(call)() == "ok"
    assert calls == 2


@pytest.mark.parametrize("status", [400, 403, 404])
async def test_permanent_status_is_not_retried(policy: RetryPolicy, status: int) -> None:
    """Отказ, который повтор не починит, поднимается сразу.

    И сразу помечается терминальным: движок по этому признаку просит api
    уведомить пользователя, не дожидаясь пятой попытки.
    """
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        raise _http_error(status)

    with pytest.raises(GoogleApiError) as error:
        await policy(call)()

    assert calls == 1
    assert error.value.status_code == status
    assert error.value.terminal is True


@pytest.mark.parametrize(
    "error",
    [TimeoutError("read timed out"), ConnectionResetError(), ssl.SSLError(),
     httplib2.HttpLib2Error()],
)
async def test_network_errors_are_retried(policy: RetryPolicy, error: Exception) -> None:
    """Сетевые сбои повторяются наравне с 5xx.

    Синхронный SDK бросает их **мимо** `HttpError`, и без этой ветки они
    проходили бы все `except` движка и роняли весь проход.
    """
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise error
        return "ok"

    assert await policy(call)() == "ok"
    assert calls == 2


async def test_retries_are_exhausted(policy: RetryPolicy) -> None:
    """После исчерпания повторов ошибка выходит наружу.

    Не терминальной: 500 — это сбой Google, и когда-нибудь он пройдёт сам.
    """
    calls = 0

    async def call() -> str:
        nonlocal calls
        calls += 1
        raise _http_error(500)

    with pytest.raises(GoogleApiError) as error:
        await policy(call)()

    assert calls == 3  # первая попытка плюс два повтора
    assert error.value.terminal is False
