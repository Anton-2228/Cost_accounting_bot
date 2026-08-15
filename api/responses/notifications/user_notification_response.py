"""Response-схема сообщения пользователю."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import NotificationKind


class UserNotificationResponse(BaseModel):
    """Готовый русский текст, который бот печатает как есть.

    Текст здесь, а не в боте, потому что рождается в фоновой работе: у неё нет
    HTTP-ответа, куда положить код ошибки, и собирается он из данных документа.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: NotificationKind
    text: str
    created_at: datetime
