"""Клиент учёта обращений к модели."""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.ai import LlmUsage
from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import LlmEntityKind, LlmOperation


class LlmUsagesClient:
    """Запись замеров: во что обошёлся вызов модели."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def record(
        self,
        spreadsheet_id: int,
        *,
        usage: LlmUsage,
        operation: LlmOperation,
        entity_kind: LlmEntityKind | None = None,
        entity_id: int | None = None,
    ) -> None:
        """Записывает один состоявшийся вызов модели.

        Ответ не разбирается: записанная строка вызывающему не нужна ничем —
        она нужна будущим запросам к базе.
        """
        await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/llm-usages",
            body={
                "operation": operation.value,
                "entity_kind": entity_kind.value if entity_kind is not None else None,
                "entity_id": entity_id,
                "model": usage.model,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
                "cost": str(usage.cost) if usage.cost is not None else None,
                "raw_usage": usage.raw,
            },
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
