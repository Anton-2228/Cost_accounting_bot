"""Доменные модели разобранного чека."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.core.types import PositiveMoneyDecimal


class CheckItem(BaseModel):
    """Одна позиция чека, уже разложенная ботом по категории.

    Сумма без знака: знак поставит вид категории, как и для обычной операции.
    `product_type` может отсутствовать — значит, тип определить не удалось и
    кэшировать нечего.
    """

    model_config = ConfigDict(from_attributes=True)

    product_name: str
    product_type: str | None = None
    category_id: int
    amount: PositiveMoneyDecimal


class ProductTypeAssignment(BaseModel):
    """Новый тип товара, который пользователь закрепил за категорией."""

    model_config = ConfigDict(from_attributes=True)

    category_id: int
    product_type: str
