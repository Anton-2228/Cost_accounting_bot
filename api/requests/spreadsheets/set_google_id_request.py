"""Request-схема привязки созданного Google-документа."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants


class SetGoogleIdRequest(BaseModel):
    """Тело служебного запроса от `google_sheets_service`.

    Повторный вызов с тем же значением безопасен: сервис мог создать документ и
    потерять ответ. Попытка привязать **другой** документ — 409.
    """

    model_config = ConfigDict(extra="forbid")

    google_spreadsheet_id: str = Field(
        min_length=1,
        max_length=constants.GOOGLE_SPREADSHEET_ID_MAX_LENGTH,
    )
