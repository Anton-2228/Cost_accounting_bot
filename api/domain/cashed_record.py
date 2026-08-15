"""Доменная модель выученного соответствия «товар → тип»."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CashedRecord(BaseModel):
    """Кэш, позволяющий не спрашивать модель об уже знакомых товарах."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    product_name: str
    product_type: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
