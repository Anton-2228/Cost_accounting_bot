"""Учёт денег, потраченных на обращения к модели."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.llm_usage import LlmUsage
from api.enums import LlmEntityKind, LlmOperation
from api.exceptions.base import NotFoundError
from api.repositories.llm_usage_repository import LlmUsageRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services.base import BaseSpreadsheetService


class LlmUsageService(BaseSpreadsheetService):
    """Запись и чтение замеров обращений к модели.

    Готовность документа не проверяется — модель зовут при разборе чека, и
    наличие Google-таблицы к расходу на неё отношения не имеет.

    Чтение ничего не суммирует: наружу уезжают сами замеры. Итоги собирает тот,
    кто показывает отчёт, потому что раскладываются они по учётным периодам, а
    те считаются в часовом поясе документа.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        usages: LlmUsageRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._usages = usages

    async def list_for_spreadsheet(self, spreadsheet_id: int) -> list[LlmUsage]:
        """Все замеры документа, в том числе отвязанного.

        Документ здесь ищется с `include_deleted=True`, а не через `_get`:
        отвязывание мягкое, и `_get` отдал бы 404 ровно на том случае, ради
        которого чтение и появилось — на истории трат по документу, которым
        больше не пользуются.
        """
        if await self._spreadsheets.get_by_id(spreadsheet_id, include_deleted=True) is None:
            raise NotFoundError("spreadsheet")
        return await self._usages.list_by_spreadsheet(spreadsheet_id)

    async def record(
        self,
        spreadsheet_id: int,
        *,
        operation: LlmOperation,
        entity_kind: LlmEntityKind | None,
        entity_id: int | None,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost: Decimal | None,
        raw_usage: dict[str, Any],
    ) -> LlmUsage:
        """Записывает один состоявшийся вызов модели."""
        await self._get(spreadsheet_id)
        usage = await self._usages.add(
            LlmUsage(
                spreadsheet_id=spreadsheet_id,
                operation=operation,
                entity_kind=entity_kind,
                entity_id=entity_id,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost=cost,
                raw_usage=raw_usage,
            )
        )
        await self._commit()
        return usage
