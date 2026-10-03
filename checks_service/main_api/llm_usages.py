"""Клиент учёта обращений к модели в основном api."""

from __future__ import annotations

import httpx

from checks_service.main_api.http import ApiHttpClient
from checks_service.qr_vision import QrVisionUsage

#: Вид обращения. Зеркало `api.enums.LlmOperation.QR_PHOTO_FALLBACK`.
QR_PHOTO_FALLBACK = "QR_PHOTO_FALLBACK"


class LlmUsagesApiClient:
    """Записывает в api, во что обошёлся вызов модели."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def record_qr_fallback(self, spreadsheet_id: int, usage: QrVisionUsage) -> None:
        """Записывает расход на чтение QR с фото."""
        await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/llm-usages",
            body={
                "operation": QR_PHOTO_FALLBACK,
                "model": usage.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "cost": str(usage.cost) if usage.cost is not None else None,
                "raw_usage": usage.raw,
            },
            expected=httpx.codes.CREATED,
        )
