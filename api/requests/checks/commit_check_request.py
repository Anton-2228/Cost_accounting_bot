"""Request-схема записи разобранного чека."""

from __future__ import annotations

from datetime import date

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
    #: День, которым датировать операции чека. Необязателен, и пустое значение
    #: означает ровно то, что эндпоинт делал до его появления, — сегодняшний
    #: день документа; второго смысла у пустоты тут нет. Необязательность здесь
    #: не вежливость, а условие выката: `extra="forbid"` выше отвергает запрос
    #: целиком, так что обязательное поле связало бы выкат api и бота в обе
    #: стороны, а необязательное — только в одну.
    #:
    #: Диапазон не ограничивается схемой: допустимость дня определяет учётный
    #: период документа, а не календарь, и проверяется в
    #: :meth:`api.services.check_service.CheckService.commit_check`.
    added_at: date | None = None
    items: list[CheckItemRequest] = Field(min_length=1)
    new_product_types: list[ProductTypeAssignmentRequest] = []
