"""Response-схема записанного замера."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from api.enums import LlmEntityKind, LlmOperation


class LlmUsageResponse(BaseModel):
    """Записанный замер.

    `raw_usage` наружу не отдаётся: он нужен будущим вопросам к базе, а
    клиенту — нет, он сам его и прислал.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    operation: LlmOperation
    entity_kind: LlmEntityKind | None
    entity_id: int | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: Decimal | None
    created_at: datetime
