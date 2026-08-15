"""Request-схема одной позиции разобранного чека."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants
from api.core.types import PositiveMoneyDecimal


class CheckItemRequest(BaseModel):
    """Позиция чека, уже разложенная ботом по категории.

    `product_type` может отсутствовать: тип определить не удалось, и кэшировать
    нечего.
    """

    model_config = ConfigDict(extra="forbid")

    product_name: str = Field(min_length=1, max_length=constants.PRODUCT_NAME_MAX_LENGTH)
    product_type: str | None = Field(default=None, max_length=constants.PRODUCT_TYPE_MAX_LENGTH)
    category_id: int = Field(gt=0)
    amount: PositiveMoneyDecimal
