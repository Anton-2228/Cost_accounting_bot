"""Request-схема закрепления типа товара за категорией."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants


class ProductTypeAssignmentRequest(BaseModel):
    """Новый тип товара, который пользователь закрепил за категорией."""

    model_config = ConfigDict(extra="forbid")

    category_id: int = Field(gt=0)
    product_type: str = Field(min_length=1, max_length=constants.PRODUCT_TYPE_MAX_LENGTH)
