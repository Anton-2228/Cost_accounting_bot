"""Доменная модель соответствия «адресат → лист документа»."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import SheetTarget


class SheetMapping(BaseModel):
    """Где физически лежит лист. Наличие записи означает «лист создан»."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    target: SheetTarget
    period_id: int | None = None
    google_sheet_id: int
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
