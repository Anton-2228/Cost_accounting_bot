"""Request-схема выдачи доступа к документу."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants
from api.enums import AccessRole


class AddAccessRequest(BaseModel):
    """Тело запроса добавления почты с доступом."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=constants.EMAIL_MAX_LENGTH)
    role: AccessRole = AccessRole.WRITER
