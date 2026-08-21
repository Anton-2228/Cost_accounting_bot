"""Репозиторий учёта обращений к модели."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.llm_usage import LlmUsage
from api.mappers.llm_usage_mapper import LlmUsageMapper
from api.orm.llm_usage import LlmUsageORM
from api.repositories.base import BaseRepository


class LlmUsageRepository(BaseRepository[LlmUsageORM, LlmUsage]):
    """Доступ к замерам обращений к модели.

    Читается таблица ровно одним разрезом — «все замеры одного документа», — и
    ничего не агрегирует. Сумму собирает тот, кто показывает отчёт: траты
    раскладываются по учётным периодам, а границы периода известны только
    вместе с часовым поясом документа, и считать их в SQL значило бы завести
    здесь вторую копию календарной логики из `periods`.
    """

    orm_type = LlmUsageORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LlmUsageMapper())

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[LlmUsage]:
        """Все замеры документа в хронологическом порядке.

        Порядок и фильтр совпадают с индексом
        `ix_llm_usages_spreadsheet_id_created_at`, ради которого он и заведён.

        Мягкое удаление здесь ни при чём: строки этой таблицы не удаляются
        никогда, в том числе вместе с документом.
        """
        rows = (
            await self._session.scalars(
                select(LlmUsageORM)
                .where(LlmUsageORM.spreadsheet_id == spreadsheet_id)
                .order_by(LlmUsageORM.created_at, LlmUsageORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)
