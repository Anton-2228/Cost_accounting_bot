"""Request-схема добавления операции."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants
from api.core.types import PositiveMoneyDecimal
from api.enums import Currency


class CreateRecordRequest(BaseModel):
    """Тело запроса добавления операции.

    Сумма строго положительна. Расход это или доход, определяет вид категории —
    поэтому «минус» от клиента не может перевернуть операцию.

    Валюта обязательна и относится к самой сумме. Значения по умолчанию нет
    намеренно: подставленная валюта молча оказалась бы там, где клиент про неё
    просто забыл, и отличить её от названной было бы нечем.

    Период не передаётся: он определяется сегодняшней датой в часовом поясе
    документа и создаётся при необходимости. День внутри периода — передаётся,
    см. `added_at`.
    """

    model_config = ConfigDict(extra="forbid")

    category_id: int = Field(gt=0)
    #: День, которым датировать операцию. Необязателен, и пустое значение
    #: означает ровно то, что эндпоинт делал до его появления, — сегодняшний
    #: день документа; второго смысла у пустоты тут нет. Необязательность здесь
    #: не вежливость, а условие выката: `extra="forbid"` выше отвергает запрос
    #: целиком, так что обязательное поле связало бы выкат api и бота в обе
    #: стороны, а необязательное — только в одну.
    #:
    #: Диапазон не ограничивается схемой: допустимость дня определяет учётный
    #: период документа, а не календарь, и проверяется в
    #: :meth:`api.services.record_service.RecordService.create`.
    added_at: date | None = None
    amount: PositiveMoneyDecimal
    currency: Currency
    notes: str = Field(default="", max_length=constants.NOTES_MAX_LENGTH)
    product_name: str | None = Field(default=None, max_length=constants.PRODUCT_NAME_MAX_LENGTH)
    product_type: str | None = Field(default=None, max_length=constants.PRODUCT_TYPE_MAX_LENGTH)
