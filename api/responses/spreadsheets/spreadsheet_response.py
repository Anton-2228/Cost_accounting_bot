"""Response-схема учётной таблицы."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.core.types import ResetDay


class SpreadsheetResponse(BaseModel):
    """Учётная таблица в ответе.

    Пустой `google_spreadsheet_id` — рабочее состояние «документ в Google ещё
    предстоит создать», по нему бот и понимает, что ссылку давать рано.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    google_spreadsheet_id: str | None
    title: str
    reset_day: ResetDay
    timezone: str
