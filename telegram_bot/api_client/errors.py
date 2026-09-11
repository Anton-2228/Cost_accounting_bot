"""Типизированные ошибки вызова api.

Транспорт превращает конверт ошибки `{code, message, details}` в исключение
нужного класса, а команды ловят то, что ожидают по смыслу. Текст для
пользователя здесь не появляется: его подбирает :mod:`telegram_bot.errors` —
один раз, в одном месте и на языке обращения.
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Api ответил ошибкой."""

    def __init__(
        self,
        status_code: int,
        *,
        code: str = "",
        message: str = "",
        details: Any = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details if isinstance(details, dict) else {}
        super().__init__(f"api {status_code} {code}: {message}")


class ApiNotFoundError(ApiError):
    """404: запрошенного ресурса нет."""

    @property
    def resource(self) -> str:
        """Что именно не найдено: `spreadsheet`, `category`, `record`, ...

        Api кладёт это в `details.resource`, и без него все 404 были бы
        неразличимы: «нет такой категории» и «нет таблицы» требуют разных
        подсказок пользователю.
        """
        return str(self.details.get("resource", ""))


class ApiConflictError(ApiError):
    """409: состояние ресурса не позволяет выполнить операцию."""

    @property
    def reason(self) -> str:
        """Машинный признак конфликта из `details.reason`.

        Например `spreadsheet_exists` или «документ ещё не создан» — второй
        случай встречается сразу после `/start` и означает не ошибку, а
        ожидание.
        """
        return str(self.details.get("reason", ""))


class ApiValidationError(ApiError):
    """422: данные корректны по формату, но нарушают правило предметной области.

    `message` пользователю не показывается: он на одном языке для всех и
    написан для журнала. Текст подбирается по :attr:`reason`, а данные для
    него — дата закрытого периода — лежат рядом в `details`.
    """

    @property
    def reason(self) -> str:
        """Машинный признак нарушенного правила из `details.reason`.

        Пуст у нарушения схемы запроса (`code == "validation_error"`): там в
        `details` лежит список полей, а не словарь с признаком.
        """
        return str(self.details.get("reason", ""))


class ApiUnavailableError(ApiError):
    """Api недоступен: сеть, таймаут или 5xx."""
