"""Request-схема создания учётной таблицы."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants
from api.core.types import ResetDay


class CreateSpreadsheetRequest(BaseModel):
    """Тело запроса создания таблицы (команда `/start`).

    `reset_day` ограничен 1..28 типом :data:`api.core.types.ResetDay`: только так
    сдвиг на месяц всегда даёт существующую дату.

    `email` необязателен. Он не выдаёт доступ сам — доступ выдаст
    `google_sheets_service`, когда создаст документ.
    """

    model_config = ConfigDict(extra="forbid")

    telegram_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=constants.SPREADSHEET_TITLE_MAX_LENGTH)
    reset_day: ResetDay
    timezone: str = Field(
        default=constants.DEFAULT_TIMEZONE,
        min_length=1,
        max_length=constants.TIMEZONE_MAX_LENGTH,
    )
    email: str | None = Field(default=None, max_length=constants.EMAIL_MAX_LENGTH)
