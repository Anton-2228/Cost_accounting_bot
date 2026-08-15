"""Response-схема категории."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.enums import CategoryKind, EntityStatus


class CategoryResponse(BaseModel):
    """Категория в ответе.

    `associations` нормализованы (нижний регистр, без дублей): по ним бот
    сопоставляет ввод пользователя с категорией.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: CategoryKind
    status: EntityStatus
    title: str
    associations: list[str]
    product_types: list[str]
