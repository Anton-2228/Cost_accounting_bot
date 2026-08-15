"""Доменная модель категории."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from api.core.text import normalize_terms
from api.enums import CategoryKind, EntityStatus


class Category(BaseModel):
    """Категория доходов или расходов.

    `associations` и `product_types` хранятся в отдельных таблицах, но в домене
    остаются обычными списками: их собирает маппер.

    Валидатор нормализует наборы при любом способе создания модели. Это не
    удобство, а обязательное условие: в дочерних таблицах стоит
    `CHECK (alias = lower(alias))`, и ненормализованное значение не пройдёт.
    Держать нормализацию в одном методе репозитория было бы недостаточно —
    путей записи несколько.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    kind: CategoryKind
    status: EntityStatus = EntityStatus.ACTIVE
    title: str
    associations: list[str] = []
    product_types: list[str] = []
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("associations", "product_types", mode="after")
    @classmethod
    def _normalize(cls, value: list[str]) -> list[str]:
        """Приводит набор к нижнему регистру, убирает дубли и сортирует."""
        return normalize_terms(value)
