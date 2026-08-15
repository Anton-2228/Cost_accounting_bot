"""Request-схема постановки чека в очередь."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class EnqueueCheckRequest(BaseModel):
    """Тело запроса «положить сырой чек в очередь».

    Готовность Google-документа для этого не требуется: чек полежит и дождётся
    разбора.
    """

    model_config = ConfigDict(extra="forbid")

    check_text: str = Field(min_length=1)
