"""Response-схема пользователя."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.enums import Language


class UserResponse(BaseModel):
    """Пользователь в ответе: кто он и на каком языке с ним говорить."""

    model_config = ConfigDict(from_attributes=True)

    telegram_id: int
    language: Language
