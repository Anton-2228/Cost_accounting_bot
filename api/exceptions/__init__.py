"""Доменные исключения и их обработчики."""

from __future__ import annotations

from api.exceptions.base import (
    AppException,
    BusinessRuleError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
)
from api.exceptions.handlers import register_exception_handlers

__all__ = [
    "AppException",
    "BusinessRuleError",
    "ConflictError",
    "ExternalServiceError",
    "NotFoundError",
    "register_exception_handlers",
]
