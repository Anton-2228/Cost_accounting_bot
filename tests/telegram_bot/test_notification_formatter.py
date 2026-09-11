"""Тесты сборки уведомлений из кода и параметров.

Api присылает не фразу, а код и данные, и печать уведомления — единственное
место, где бот собирает текст из чужих данных. Ошибиться здесь можно дважды:
не знать кода, который api шлёт, и упасть на данных, которые пришли не такими.
Первое ловится сверкой с кодом api, второе — тем, что сборка не бросает никогда.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from telegram_bot.formatting.notification_formatter import (
    KNOWN_CODES,
    LEGACY_CODE,
    NotificationFormatter,
)
from telegram_bot.i18n import CATALOGS, SUPPORTED_LANGUAGES, t

_API_ROOT = Path(__file__).resolve().parents[2] / "api"


def _api_codes() -> set[str]:
    """Коды уведомлений, которые может отправить api.

    Берутся из исходников, а не из вызовов: часть кодов рождается только на
    испорченном листе, и перебирать для каждого подходящий лист значило бы
    переписать здесь всю проверку листа.
    """
    codes: set[str] = set()
    messages = ast.parse((_API_ROOT / "core" / "messages.py").read_text(encoding="utf-8"))
    for node in ast.walk(messages):
        if isinstance(node, ast.keyword) and node.arg == "code":
            assert isinstance(node.value, ast.Constant)
            codes.add(str(node.value.value))
    validation = ast.parse((_API_ROOT / "validation.py").read_text(encoding="utf-8"))
    for node in ast.walk(validation):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_error"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            codes.add(f"import_error.{node.args[0].value!s}")
    return codes


class TestCoverage:
    """Бот знает ровно те коды, что шлёт api."""

    def test_every_api_code_is_known(self) -> None:
        """Код, которого бот не знает, пользователь увидел бы общей фразой."""
        assert sorted(_api_codes() - KNOWN_CODES) == []

    def test_no_dead_codes(self) -> None:
        """Код, которого api больше не шлёт, — мёртвый шаблон в пяти каталогах."""
        assert sorted(KNOWN_CODES - _api_codes()) == []

    @pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
    def test_every_code_has_a_template(self, language: object) -> None:
        """У каждого кода есть шаблон на каждом языке."""
        catalog = CATALOGS[language]  # type: ignore[index]
        assert sorted(code for code in KNOWN_CODES if f"notification.{code}" not in catalog) == []


class TestRendering:
    """Данные доводятся до вида, в котором их показывают."""

    def test_table_link_is_built_by_the_bot(self) -> None:
        """Ссылку api не присылает: бот собирает её сам, тем же шаблоном."""
        text = NotificationFormatter.render("table_ready", {"google_spreadsheet_id": "abc"})
        assert text == "Таблица готова: https://docs.google.com/spreadsheets/d/abc"

    def test_date_follows_the_language(self) -> None:
        """Дата приходит в ISO, а печатается по правилам языка."""
        text = NotificationFormatter.render("rollover_done", {"start_date": "2026-07-01"})
        assert "01.07.2026" in text
        assert "2026-07-01" not in text

    def test_sheet_error_keeps_row_and_column(self) -> None:
        """Номер строки и колонка — ровно то, что пользователь ищет в листе."""
        text = NotificationFormatter.render(
            "import_error.flag_invalid", {"row": 5, "column": "Active"}
        )
        assert text == "В категориях в 5 строке Active странный"

    def test_long_google_error_is_cut(self) -> None:
        """Ошибка Google бывает длинной, а сообщение Telegram — нет."""
        text = NotificationFormatter.render("sync_terminal", {"error": "x" * 10_000})
        assert len(text) < 4096

    def test_legacy_text_is_printed_as_is(self) -> None:
        """Строка старой версии печатается своим готовым текстом."""
        assert NotificationFormatter.render(LEGACY_CODE, {"text": "Готово"}) == "Готово"


class TestNeverRaises:
    """Что бы ни пришло, пользователь получает фразу, а api — ответ."""

    def test_unknown_code(self) -> None:
        """Код из будущей версии api не роняет доставку."""
        assert NotificationFormatter.render("from_the_future", {}) == t("notification.fallback")

    def test_missing_param(self) -> None:
        """Шаблон с фигурными скобками хуже общей фразы."""
        text = NotificationFormatter.render("import_error.unknown_id", {})
        assert text == t("notification.fallback")

    def test_broken_date(self) -> None:
        """Испорченная дата — не повод отвечать api ошибкой."""
        text = NotificationFormatter.render("rollover_done", {"start_date": "вчера"})
        assert text == t("notification.fallback")

    def test_missing_table_id(self) -> None:
        """Без идентификатора ссылку не собрать — но и падать не из-за чего."""
        assert NotificationFormatter.render("table_ready", {}) == t("notification.fallback")
