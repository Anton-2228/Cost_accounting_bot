"""Request-схема запоминания созданного листа."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants
from api.enums import SheetTarget


class UpsertSheetMappingRequest(BaseModel):
    """Тело служебного запроса от `google_sheets_service`.

    Соответствие хранит api, а не сам `google_sheets_service`: у того нет своей
    базы, и после перезапуска он иначе не знал бы, создан ли уже лист периода.

    Согласованность `target` и `period_id` проверяет сервис: это правило
    предметной области, а не формат запроса.
    """

    model_config = ConfigDict(extra="forbid")

    target: SheetTarget
    google_sheet_id: int
    title: str = Field(min_length=1, max_length=constants.GOOGLE_SHEET_TITLE_MAX_LENGTH)
    period_id: int | None = Field(default=None, gt=0)
