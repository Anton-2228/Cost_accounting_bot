"""Request-схема записи разобранного чека."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.requests.checks.check_item_request import CheckItemRequest
from api.requests.checks.product_type_assignment_request import ProductTypeAssignmentRequest


class CommitCheckRequest(BaseModel):
    """Тело запроса записи чека целиком.

    Чек приезжает одним запросом намеренно: позиции, новые типы товаров и кэш
    пишутся одной транзакцией. Разбить это на несколько запросов значило бы
    допустить состояние «половина чека в реестре».
    """

    model_config = ConfigDict(extra="forbid")

    source_id: int = Field(gt=0)
    items: list[CheckItemRequest] = Field(min_length=1)
    new_product_types: list[ProductTypeAssignmentRequest] = []
    check_json: str | None = None
