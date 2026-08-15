"""Response-схема соответствия «адресат → лист документа»."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.enums import SheetTarget


class SheetMappingResponse(BaseModel):
    """Где лежит лист. Наличие записи означает «лист уже создан»."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    target: SheetTarget
    period_id: int | None
    google_sheet_id: int
    title: str
