"""Конверт ответа об ошибке."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Единый формат ошибки.

    `code` машинный: бот подбирает по нему русский текст. `details` несёт
    подробности — например, какой именно ресурс не найден.
    """

    code: str
    message: str
    details: Any | None = None
