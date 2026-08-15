"""Response-схема учётного периода."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from api.enums import PeriodStatus


class PeriodResponse(BaseModel):
    """Период в ответе. Границы полуинтервальные: день `end_date` не входит."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    start_date: date
    end_date: date
    status: PeriodStatus
    closed_at: datetime | None
