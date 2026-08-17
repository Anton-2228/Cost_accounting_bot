"""Response-схема учётной таблицы."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.core.types import ResetDay


class SpreadsheetResponse(BaseModel):
    """Учётная таблица в ответе.

    Пустой `google_spreadsheet_id` — рабочее состояние «документ в Google ещё
    предстоит создать», по нему бот и понимает, что ссылку давать рано.

    `created_at` выдаётся наружу не ради показа: вместе с `id` он образует
    метку, которой `google_sheets_service` помечает созданный документ в Drive
    и по которой находит его при повторе. Одного `id` для этого мало — он
    уникален лишь в пределах одной жизни базы, и пересозданная база начинает
    нумерацию заново, попадая меткой в чужой документ от прежних запусков.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    google_spreadsheet_id: str | None
    title: str
    reset_day: ResetDay
    timezone: str
    created_at: datetime
