"""Тесты перевода ошибок api в русский текст и проверки доступа."""

from __future__ import annotations

import pytest

from telegram_bot.access import AccessGuard
from telegram_bot.api_client.errors import (
    ApiConflictError,
    ApiError,
    ApiNotFoundError,
    ApiUnavailableError,
    ApiValidationError,
)
from telegram_bot.errors import UNAVAILABLE_MESSAGE, UNEXPECTED_MESSAGE, ApiErrorPresenter


class TestNotFound:
    """404 различается по `details.resource`."""

    @pytest.mark.parametrize(
        ("resource", "fragment"),
        [
            ("spreadsheet", "Сначала создайте таблицу"),
            ("category", "категории"),
            ("source", "счёта"),
            ("record", "Операции с таким id"),
            ("transfer", "Перевода с таким id"),
        ],
    )
    def test_known_resources(self, resource: str, fragment: str) -> None:
        """Каждый ресурс получает свой текст.

        Без `details.resource` все 404 были бы неразличимы, и «нет такой
        категории» пришлось бы объяснять теми же словами, что «нет таблицы».
        """
        error = ApiNotFoundError(404, code="not_found", details={"resource": resource})
        assert fragment in ApiErrorPresenter.present(error)

    def test_unknown_resource_has_fallback(self) -> None:
        """Незнакомый ресурс не оставляет пользователя без ответа."""
        error = ApiNotFoundError(404, code="not_found", details={"resource": "нечто"})
        assert ApiErrorPresenter.present(error)


class TestConflict:
    """409 различается по `details.reason`."""

    def test_spreadsheet_exists(self) -> None:
        """Повторный /start объясняется и подсказывает следующий шаг."""
        error = ApiConflictError(409, code="conflict", details={"reason": "spreadsheet_exists"})
        assert "уже есть таблица" in ApiErrorPresenter.present(error)

    def test_not_ready_is_not_an_error_for_the_user(self) -> None:
        """«Документ ещё не создан» — ожидание, а не поломка.

        Это состояние наступает сразу после /start и держится, пока
        google_sheets_service не создаст таблицу, поэтому текст обещает ссылку,
        а не сообщает об отказе.
        """
        error = ApiConflictError(
            409, code="conflict", details={"reason": "spreadsheet_not_ready"}
        )
        text = ApiErrorPresenter.present(error)
        assert "создаётся" in text
        assert "пришлю ссылку" in text


class TestValidation:
    """422 печатается как есть."""

    def test_message_is_shown_verbatim(self) -> None:
        """Текст собран из данных документа, кодом его не выразить."""
        error = ApiValidationError(
            422,
            code="business_rule_violation",
            message="Период с 2026-07-01 закрыт",
        )
        assert ApiErrorPresenter.present(error) == "Период с 2026-07-01 закрыт"

    def test_empty_message_has_fallback(self) -> None:
        """Пустой текст не превращается в пустое сообщение пользователю."""
        error = ApiValidationError(422, code="business_rule_violation", message="")
        assert ApiErrorPresenter.present(error)


class TestUnavailable:
    """Недоступность api и неизвестные ошибки."""

    def test_unavailable(self) -> None:
        """Сеть, таймаут и 5xx выглядят для пользователя одинаково."""
        assert ApiErrorPresenter.present(ApiUnavailableError(0)) == UNAVAILABLE_MESSAGE

    def test_unknown_error(self) -> None:
        """Незнакомый статус тоже получает ответ, а не молчание."""
        assert ApiErrorPresenter.present(ApiError(418)) == UNEXPECTED_MESSAGE


class TestAccessGuard:
    """Список разрешённых пользователей."""

    def test_allowed(self) -> None:
        """Перечисленный id проходит."""
        assert AccessGuard([1, 2, 3]).is_allowed(2) is True

    def test_denied(self) -> None:
        """Не перечисленный — нет."""
        assert AccessGuard([1, 2, 3]).is_allowed(99) is False

    def test_empty_list_denies_everyone(self) -> None:
        """Пустой список закрывает бота, а не открывает.

        Бот, поднятый без настройки, не должен оказаться доступным всем: /start
        тратит квоту общего сервисного аккаунта Google.
        """
        assert AccessGuard([]).is_allowed(1) is False

    def test_missing_user_is_denied(self) -> None:
        """Сообщение без автора (канал, служебное) не проходит."""
        assert AccessGuard([1]).is_allowed(None) is False
