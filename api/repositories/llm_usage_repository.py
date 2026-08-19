"""Репозиторий учёта обращений к модели."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.llm_usage import LlmUsage
from api.mappers.llm_usage_mapper import LlmUsageMapper
from api.orm.llm_usage import LlmUsageORM
from api.repositories.base import BaseRepository


class LlmUsageRepository(BaseRepository[LlmUsageORM, LlmUsage]):
    """Доступ к замерам обращений к модели.

    Своих методов нет намеренно: наружу таблица только пишется, а читают её
    запросами к базе напрямую — сводки нужны разные и заранее не известны, и
    зашивать сегодняшний разрез в эндпоинт значило бы менять api под каждый
    следующий вопрос.
    """

    orm_type = LlmUsageORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, LlmUsageMapper())
