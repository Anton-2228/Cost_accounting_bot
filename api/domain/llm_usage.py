"""Доменная модель обращения к модели."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.enums import LlmEntityKind, LlmOperation


class LlmUsage(BaseModel):
    """Один состоявшийся вызов модели и его цена.

    Записывается только то, что действительно случилось: неудачные обращения
    сюда не попадают, и колонки статуса поэтому нет. `cost` пуст, если провайдер
    его не прислал, — это «неизвестно», а не «бесплатно».
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    operation: LlmOperation
    entity_kind: LlmEntityKind | None = None
    entity_id: int | None = None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: Decimal | None = None
    raw_usage: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None
