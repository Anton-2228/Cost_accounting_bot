"""Request-схема записи разобранного чека."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.requests.checks.check_item_request import CheckItemRequest
from api.requests.checks.product_type_assignment_request import ProductTypeAssignmentRequest


class CommitCheckRequest(BaseModel):
    """Тело запроса записи чека целиком.

    Чек приезжает одним запросом намеренно: позиции, новые типы товаров, кэш и
    отметка о разборе пишутся одной транзакцией. Разбить это на несколько
    запросов значило бы допустить состояние «половина чека в реестре».

    `check_id` обязателен: записывать позиции, не привязав их к строке в
    `checks`, больше незачем — именно по этой связи чек считается разобранным и
    уходит из очереди.
    """

    model_config = ConfigDict(extra="forbid")

    check_id: int = Field(gt=0)
    source_id: int = Field(gt=0)
    items: list[CheckItemRequest] = Field(min_length=1)
    new_product_types: list[ProductTypeAssignmentRequest] = []
