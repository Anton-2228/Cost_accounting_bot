"""Request-схема записи замера обращения к модели."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.enums import LlmEntityKind, LlmOperation


class RecordLlmUsageRequest(BaseModel):
    """Тело запроса «запиши, во что обошёлся вызов модели».

    Приезжает от клиента, который этот вызов и сделал: у api нет ни ключа
    провайдера, ни единого внешнего вызова, и знать цену обращения ему неоткуда.

    `model` — название, которое вернул провайдер, а не запрошенное: счёт придёт
    именно за него. `cost` необязателен — провайдер может его не прислать, и
    пустое значение означает «неизвестно», а не «бесплатно». `raw_usage`
    кладётся как пришёл: решать за будущие вопросы, какие поля провайдера
    пригодятся, здесь нельзя.
    """

    model_config = ConfigDict(extra="forbid")

    operation: LlmOperation
    entity_kind: LlmEntityKind | None = None
    entity_id: int | None = None
    model: str = Field(min_length=1)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost: Decimal | None = Field(default=None, ge=0)
    raw_usage: dict[str, Any]

    @model_validator(mode="after")
    def _check_entity_pair(self) -> Self:
        """Вид сущности и её идентификатор приезжают только вместе.

        То же самое стережёт `CHECK` в БД, но нарушение схемы должно быть 422 с
        внятным текстом, а не ошибкой целостности, которую клиенту нечем
        отличить от поломки сервера.
        """
        if (self.entity_kind is None) != (self.entity_id is None):
            raise ValueError("entity_kind и entity_id указываются вместе либо не указываются")
        return self
