"""Response-схема сообщения пользователю."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.enums import NotificationKind


class UserNotificationResponse(BaseModel):
    """Сообщение о фоновой работе: код и данные, а не готовый текст.

    Фразу на языке пользователя бот собирает по `code` из своего каталога,
    подставляя `params`. Сообщение рождается в фоновой работе, у которой нет
    HTTP-ответа, поэтому едет строкой очереди, а не кодом ошибки в ответе.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: NotificationKind
    code: str
    params: dict[str, Any]
    created_at: datetime
