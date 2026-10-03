"""HTTP-клиент сайдкара qr_vision.

Сайдкар — Node-процесс с харнессом pi: у pi нет SDK для Python, поэтому модель
зовётся там, а сюда приезжает готовый ответ. Клиент никогда не бросает: фолбек
необязателен, и любой его сбой для пользователя — то же «QR не найден», что и
без него. Причина сбоя уходит в журнал.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from checks_service.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class QrVisionUsage:
    """Во что обошёлся вызов: счёт pi по всем попыткам модели."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    #: В валюте провайдера (доллары OpenRouter). `None` — неизвестно, не ноль.
    cost: Decimal | None
    #: Блок `usage` сайдкара целиком — уезжает в `llm_usages.raw_usage`.
    raw: dict[str, Any]


@dataclass(frozen=True)
class QrVisionResult:
    """Ответ сайдкара: строка QR (или `None`) и расход, если модель звали."""

    qr: str | None
    usage: QrVisionUsage | None


class QrVisionClient:
    """Просит сайдкар прочитать QR с фото."""

    def __init__(self, base_url: str, *, timeout: float) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def decode(self, data: bytes, *, mime_type: str) -> QrVisionResult | None:
        """Строка QR и расход; `None` — сайдкар недоступен или ответил не то."""
        try:
            response = await self._client.post(
                "/decode",
                json={"image": base64.b64encode(data).decode("ascii"), "mimeType": mime_type},
            )
        except httpx.HTTPError as error:
            logger.warning("Фолбек QR недоступен: %r", error)
            return None
        if response.status_code != httpx.codes.OK:
            logger.warning("Фолбек QR ответил %s: %s", response.status_code, response.text[:200])
            return None
        try:
            return _parse(response.json())
        except (ValueError, TypeError, KeyError) as error:
            logger.warning("Фолбек QR прислал непонятный ответ: %r", error)
            return None


def _parse(body: dict[str, Any]) -> QrVisionResult:
    qr = body.get("qr")
    if qr is not None and not isinstance(qr, str):
        raise TypeError(f"qr — не строка: {type(qr).__name__}")
    return QrVisionResult(qr=qr or None, usage=_parse_usage(body.get("usage"), body.get("model")))


def _parse_usage(usage: Any, model: Any) -> QrVisionUsage | None:
    """Расход; `None`, если модель так и не ответила и платить не за что."""
    if not isinstance(usage, dict) or not model:
        return None
    prompt = int(usage["input"]) + int(usage.get("cacheRead", 0)) + int(usage.get("cacheWrite", 0))
    completion = int(usage["output"])
    total = int(usage.get("totalTokens", prompt + completion))
    if total == 0:
        # Запрос не дошёл до модели (ключ, сеть): счёта за него не будет.
        return None
    return QrVisionUsage(
        model=str(model),
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost=_cost(usage.get("cost")),
        raw=dict(usage),
    )


def _cost(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        cost = Decimal(str(value))
    except InvalidOperation:
        return None
    return cost if cost >= 0 else None
