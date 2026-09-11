"""Request-схема смены языка пользователя."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.enums import Language


class SetLanguageRequest(BaseModel):
    """Тело `PUT /users/{telegram_id}/language`."""

    model_config = ConfigDict(extra="forbid")

    language: Language
