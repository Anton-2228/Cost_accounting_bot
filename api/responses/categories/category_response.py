"""Response-схема категории."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.enums import CategoryKind, EntityStatus


class CategoryResponse(BaseModel):
    """Категория в ответе.

    `associations` нормализованы (нижний регистр, без дублей): по ним бот
    сопоставляет ввод пользователя с категорией.

    `is_default` — категория по умолчанию своего вида. Бот узнаёт корзину
    расходов по нему, а не по названию: название на языке пользователя и
    может быть переименовано в листе.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: CategoryKind
    status: EntityStatus
    title: str
    is_default: bool
    associations: list[str]
    product_types: list[str]
