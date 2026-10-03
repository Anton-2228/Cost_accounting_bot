"""Тесты клиента сайдкара qr_vision.

Клиент не бросает никогда: фолбек необязателен, и любой его сбой для
пользователя — обычное «QR не найден».
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from checks_service.qr_vision import QrVisionClient

OK_USAGE: dict[str, Any] = {
    "input": 1500,
    "output": 40,
    "cacheRead": 0,
    "cacheWrite": 0,
    "totalTokens": 1540,
    "cost": 0.0123,
}
OK_BODY: dict[str, Any] = {
    "qr": "t=20260725T1507&s=1214.95&fn=1&i=2&fp=3&n=1",
    "model": "anthropic/claude-opus-5.5",
    "usage": OK_USAGE,
}


def _client(handler: Any) -> QrVisionClient:
    client = QrVisionClient("http://qr-vision.test", timeout=1)
    client._client = httpx.AsyncClient(  # noqa: SLF001 — подмена транспорта в тесте
        base_url="http://qr-vision.test", transport=httpx.MockTransport(handler)
    )
    return client


async def test_sends_the_image_and_parses_the_answer() -> None:
    """Фото уезжает base64 с типом, ответ разбирается вместе с расходом."""
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    result = await _client(handler).decode(b"\x01\x02", mime_type="image/jpeg")

    assert seen == {"image": "AQI=", "mimeType": "image/jpeg"}
    assert result is not None
    assert result.qr == OK_BODY["qr"]
    assert result.usage is not None
    assert result.usage.model == "anthropic/claude-opus-5.5"
    assert result.usage.prompt_tokens == 1500
    assert result.usage.completion_tokens == 40
    assert result.usage.total_tokens == 1540
    assert result.usage.cost == Decimal("0.0123")
    assert result.usage.raw == OK_BODY["usage"]


async def test_model_that_never_answered_costs_nothing() -> None:
    """Нулевой расход — запрос до модели не дошёл, записывать нечего."""
    body = {
        **OK_BODY,
        "qr": None,
        "usage": {**OK_USAGE, "input": 0, "output": 0, "totalTokens": 0},
    }

    result = await _client(lambda _: httpx.Response(200, json=body)).decode(
        b"x", mime_type="image/png"
    )

    assert result is not None
    assert result.qr is None
    assert result.usage is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, json={"code": "model_failed"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"qr": 42, "usage": None, "model": None}),
    ],
)
async def test_bad_answers_are_none(response: httpx.Response) -> None:
    """Не 200 или непонятный ответ — `None`, а не исключение."""
    assert await _client(lambda _: response).decode(b"x", mime_type="image/png") is None


async def test_network_failure_is_none() -> None:
    """Сайдкар недоступен или не уложился в таймаут — `None`."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    assert await _client(handler).decode(b"x", mime_type="image/png") is None
