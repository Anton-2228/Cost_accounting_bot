"""Request-схема добавления операции."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants
from api.core.types import PositiveMoneyDecimal
from api.enums import Currency


class CreateRecordRequest(BaseModel):
    """Тело запроса добавления операции.

    Сумма строго положительна. Расход это или доход, определяет вид категории —
    поэтому «минус» от клиента не может перевернуть операцию.

    Валюта обязательна и относится к самой сумме, а не к счёту: динарами
    можно расплатиться с еврового счёта. Значения по умолчанию нет намеренно
    — «валюта счёта, если не сказано иное» молча подставлялась бы там, где
    клиент про валюту просто забыл.

    Период не передаётся: он определяется сегодняшней датой в часовом поясе
    документа и создаётся при необходимости.
    """

    model_config = ConfigDict(extra="forbid")

    category_id: int = Field(gt=0)
    source_id: int = Field(gt=0)
    amount: PositiveMoneyDecimal
    currency: Currency
    notes: str = Field(default="", max_length=constants.NOTES_MAX_LENGTH)
    product_name: str | None = Field(default=None, max_length=constants.PRODUCT_NAME_MAX_LENGTH)
    product_type: str | None = Field(default=None, max_length=constants.PRODUCT_TYPE_MAX_LENGTH)
