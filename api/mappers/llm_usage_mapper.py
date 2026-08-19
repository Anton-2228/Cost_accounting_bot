"""Маппер обращения к модели."""

from __future__ import annotations

from api.domain.llm_usage import LlmUsage
from api.mappers.base import BaseMapper
from api.orm.llm_usage import LlmUsageORM


class LlmUsageMapper(BaseMapper[LlmUsageORM, LlmUsage]):
    """Замер: токены, стоимость и повод обращения."""

    def to_domain(self, orm: LlmUsageORM) -> LlmUsage:
        """Преобразует ORM-объект в доменную модель."""
        return LlmUsage(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            operation=orm.operation,
            entity_kind=orm.entity_kind,
            entity_id=orm.entity_id,
            model=orm.model,
            prompt_tokens=orm.prompt_tokens,
            completion_tokens=orm.completion_tokens,
            total_tokens=orm.total_tokens,
            cost=orm.cost,
            raw_usage=orm.raw_usage,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: LlmUsage) -> LlmUsageORM:
        """Создаёт ORM-объект из доменной модели."""
        return LlmUsageORM(
            spreadsheet_id=domain.spreadsheet_id,
            operation=domain.operation,
            entity_kind=domain.entity_kind,
            entity_id=domain.entity_id,
            model=domain.model,
            prompt_tokens=domain.prompt_tokens,
            completion_tokens=domain.completion_tokens,
            total_tokens=domain.total_tokens,
            cost=domain.cost,
            raw_usage=domain.raw_usage,
        )
