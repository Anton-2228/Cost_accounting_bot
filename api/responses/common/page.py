"""Конверт ответа для списка."""

from __future__ import annotations

from pydantic import BaseModel


class Page[T](BaseModel):
    """Страница результатов вместе с метаданными пагинации."""

    items: list[T]
    total: int
    limit: int
    offset: int
