"""Response-схема выученного соответствия «товар → тип»."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CashedRecordResponse(BaseModel):
    """Кэш, позволяющий боту не спрашивать модель о знакомом товаре."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_name: str
    product_type: str
