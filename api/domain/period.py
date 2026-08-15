"""Доменная модель учётного периода."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from api.enums import PeriodStatus


class Period(BaseModel):
    """Учётный «месяц»: полуинтервал ``[start_date, end_date)``.

    День `end_date` в период **не входит** — он уже начало следующего.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    start_date: date
    end_date: date
    status: PeriodStatus = PeriodStatus.OPEN
    closed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def contains(self, day: date) -> bool:
        """Принадлежит ли дата этому периоду."""
        return self.start_date <= day < self.end_date
