"""Иерархия доменных исключений приложения.

Каждое исключение несёт HTTP-статус и машинный код, в которые его превращает
`register_exception_handlers`. Человекочитаемый русский текст живёт в боте и
подбирается по коду; исключение — сообщения о разборе листа, которые строятся
из пользовательских данных и номеров строк, поэтому едут как данные.
"""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """Базовое прикладное исключение."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        self.message = message
        self.details = details
        super().__init__(message)


class NotFoundError(AppException):
    """Запрашиваемый ресурс не найден."""

    status_code = 404
    code = "not_found"

    def __init__(self, resource: str, message: str | None = None) -> None:
        super().__init__(message or f"{resource} не найден", details={"resource": resource})


class ConflictError(AppException):
    """Нарушение уникальности или конфликт состояния ресурса."""

    status_code = 409
    code = "conflict"


class BusinessRuleError(AppException):
    """Данные корректны по формату, но недопустимы по правилам предметной области."""

    status_code = 422
    code = "business_rule_violation"


class ExternalServiceError(AppException):
    """Ошибка взаимодействия с внешним сервисом."""

    status_code = 502
    code = "external_service_error"
