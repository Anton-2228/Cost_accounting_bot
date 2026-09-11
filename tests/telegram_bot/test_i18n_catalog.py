"""Тесты каталогов текстов и подстановки по ключу.

Каталог — единственное место, где живут формулировки, и ошибиться в нём можно
молча: ключ, которого нет, печатается пользователю самим ключом, а
подстановка, которой нет в переводе, — пропадает. Поэтому соответствие
каталогов друг другу и коду проверяется здесь, а не глазами в переписке.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from telegram_bot.api_client.models import Currency
from telegram_bot.commands.table_unlink import _same_phrase
from telegram_bot.errors import CONFLICT_KEYS, NOT_FOUND_RESOURCES
from telegram_bot.i18n import (
    CATALOGS,
    SUPPORTED_LANGUAGES,
    Language,
    LocaleFormat,
    language_scope,
    t,
    t_in,
)
from telegram_bot.i18n.catalog import CatalogError, load_language, placeholders
from telegram_bot.parsers import OnboardingParser, currency_parser

#: Исходный каталог: остальные переводятся с него.
_SOURCE = Language.RU

_BOT_ROOT = Path(__file__).resolve().parents[2] / "telegram_bot"


def _literal_keys() -> set[str]:
    """Ключи, которые код бота передаёт в `t` и `t_in` литералом.

    Ключи, собранные на ходу (`f"currency.sign.{…}"`), сюда не попадают — их
    семейства проверяются отдельно, по перечислениям, из которых они строятся.
    """
    keys: set[str] = set()
    for path in _BOT_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            position = {"t": 0, "t_in": 1}.get(node.func.id)
            if position is None or len(node.args) <= position:
                continue
            argument = node.args[position]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                keys.add(argument.value)
    return keys


class TestParity:
    """Каталоги всех языков совпадают по ключам и подстановкам."""

    def test_source_catalog_is_supported(self) -> None:
        """Исходный каталог загружен и доступен для выбора."""
        assert _SOURCE in SUPPORTED_LANGUAGES

    @pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
    def test_same_keys(self, language: Language) -> None:
        """Ключ, забытый в переводе, печатался бы на языке по умолчанию."""
        source = CATALOGS[_SOURCE].keys()
        target = CATALOGS[language].keys()
        assert sorted(source - target) == []
        assert sorted(target - source) == []

    @pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
    def test_same_placeholders(self, language: Language) -> None:
        """Перевод подставляет ровно те же значения, что исходник.

        Лишняя подстановка роняет `format`, а пропавшая молча теряет данные:
        сумму, название категории, номер строки.
        """
        source = CATALOGS[_SOURCE]
        target = CATALOGS[language]
        mismatched = [
            key
            for key in source
            if key in target and placeholders(source[key]) != placeholders(target[key])
        ]
        assert mismatched == []

    @pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
    def test_no_empty_texts(self, language: Language) -> None:
        """Пустой текст Telegram не отправит вовсе."""
        assert [key for key, value in CATALOGS[language].items() if not value.strip()] == []


class TestCodeReferences:
    """Всё, что код просит у каталога, в каталоге есть."""

    def test_every_literal_key_exists(self) -> None:
        """Опечатка в ключе иначе всплыла бы только в переписке."""
        assert sorted(_literal_keys() - CATALOGS[_SOURCE].keys()) == []

    def test_not_found_family_is_complete(self) -> None:
        """У каждого ресурса 404 со своей формулировкой она есть."""
        for resource in [*NOT_FOUND_RESOURCES, "default"]:
            assert f"errors.not_found.{resource}" in CATALOGS[_SOURCE]

    def test_conflict_family_is_complete(self) -> None:
        """Каждый признак 409 ведёт к существующему тексту."""
        for key in [*CONFLICT_KEYS.values(), "errors.conflict.default"]:
            assert key in CATALOGS[_SOURCE]

    def test_every_currency_has_a_sign(self) -> None:
        """Валюта без знака уронила бы печать суммы на полпути."""
        for currency in Currency:
            assert f"currency.sign.{currency.value}" in CATALOGS[_SOURCE]


class TestLoader:
    """Испорченный каталог не читается вовсе."""

    def test_broken_template_is_rejected(self, tmp_path: Path) -> None:
        """Незакрытая скобка — ошибка на старте, а не на сообщении."""
        (tmp_path / "strings.toml").write_text('broken = "Сумма {amount"\n', encoding="utf-8")
        with pytest.raises(CatalogError):
            load_language(tmp_path)

    def test_non_string_is_rejected(self, tmp_path: Path) -> None:
        """Число вместо строки — ошибка каталога, а не текст «1»."""
        (tmp_path / "strings.toml").write_text("count = 1\n", encoding="utf-8")
        with pytest.raises(CatalogError):
            load_language(tmp_path)

    def test_duplicate_key_is_rejected(self, tmp_path: Path) -> None:
        """Ключ из `.txt` не может молча перекрыть ключ из TOML."""
        (tmp_path / "strings.toml").write_text('[text]\nwelcome = "a"\n', encoding="utf-8")
        (tmp_path / "WELCOME.txt").write_text("b", encoding="utf-8")
        with pytest.raises(CatalogError):
            load_language(tmp_path)

    def test_text_files_become_keys(self, tmp_path: Path) -> None:
        """`WELCOME.txt` читается как `text.welcome`, без пустых краёв."""
        (tmp_path / "strings.toml").write_text('[a]\nb = "c"\n', encoding="utf-8")
        (tmp_path / "WELCOME.txt").write_text("\nПривет\n", encoding="utf-8")
        assert load_language(tmp_path) == {"a.b": "c", "text.welcome": "Привет"}


class TestTranslator:
    """Подстановка никогда не роняет обращение."""

    def test_missing_key_is_printed_as_is(self) -> None:
        """Лучше ключ в ответе, чем молчание вместо ответа."""
        assert t("no.such.key") == "no.such.key"

    def test_broken_params_give_the_template(self) -> None:
        """Забытая подстановка не превращается в исключение."""
        assert t("format.record.id") == CATALOGS[_SOURCE]["format.record.id"]

    def test_explicit_language(self) -> None:
        """`t_in` берёт язык из аргумента, а не из обращения."""
        assert t_in(_SOURCE, "buttons.cancel") == CATALOGS[_SOURCE]["buttons.cancel"]

    def test_scope_is_restored(self) -> None:
        """Вложенная область возвращает внешний язык, а не умолчание."""
        with language_scope(_SOURCE):
            inner = t("buttons.cancel")
        assert inner == CATALOGS[_SOURCE]["buttons.cancel"]


class TestLocaleFormat:
    """Числа и даты по правилам языка."""

    def test_russian_is_unchanged(self) -> None:
        """Русский вывод тот же, что до перехода на Babel."""
        with language_scope(Language.RU):
            assert LocaleFormat.decimal(Decimal("1234567.5"), 2) == "1 234 567,50"
            assert LocaleFormat.integer(300000) == "300 000"
            assert LocaleFormat.day(date(2026, 7, 1)) == "01.07.2026"
            assert LocaleFormat.moment(datetime(2026, 7, 25, 15, 7)) == "25.07.2026 15:07"

    def test_no_non_breaking_spaces(self) -> None:
        """Разряды разделяются обычным пробелом, как бы их ни разделял CLDR."""
        with language_scope(Language.RU):
            text = LocaleFormat.decimal(Decimal("1234567"), 2)
        assert "\u00a0" not in text
        assert "\u202f" not in text


    @pytest.mark.parametrize(
        ("language", "expected"),
        [
            (Language.RU, "1 234 567,50"),
            (Language.EN, "1,234,567.50"),
            (Language.HI, "12,34,567.50"),
            (Language.ES, "1.234.567,50"),
            (Language.FR, "1 234 567,50"),
        ],
    )
    def test_grouping_follows_the_language(self, language: Language, expected: str) -> None:
        """Разряды и дробь — по CLDR; у хинди разряды группируются лакхами."""
        with language_scope(language):
            assert LocaleFormat.decimal(Decimal("1234567.5"), 2) == expected

    @pytest.mark.parametrize(
        ("language", "expected"),
        [
            (Language.RU, "01.07.2026"),
            (Language.EN, "7/1/2026"),
            (Language.HI, "1/7/2026"),
            (Language.ES, "1/7/2026"),
            (Language.FR, "01/07/2026"),
        ],
    )
    def test_dates_follow_the_language(self, language: Language, expected: str) -> None:
        """Порядок дня и месяца — тот, к которому привык читатель."""
        with language_scope(language):
            assert LocaleFormat.day(date(2026, 7, 1)) == expected


class TestInputAcrossLanguages:
    """Всё, чему каталог учит пользователя, бот понимает — на любом языке."""

    @pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
    def test_currency_hint_words_are_understood(self, language: Language) -> None:
        """Подсказка, которую бот не понимает, учила бы ошибке."""
        for word in CATALOGS[language]["parse.currency.hint"].split(", "):
            assert currency_parser.parse(word) is not None, word

    @pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
    def test_help_examples_are_understood(self, language: Language) -> None:
        """Пример `/add` из справки обязан работать, как написан."""
        examples = re.findall(r"/add (\S+) \d", CATALOGS[language]["text.help_commands"])
        assert examples
        for word in examples:
            assert currency_parser.parse(word) is not None, word

    @pytest.mark.parametrize(
        "word", ["-", "нет", "Skip", "NON", "saltar", "नहीं", "छोड़ें", " пропустить "]
    )
    def test_skip_words_of_every_language(self, word: str) -> None:
        """Сменивший язык отвечает по привычке — и это не ошибка ввода."""
        assert OnboardingParser.is_skip(word)
        assert OnboardingParser.is_skip(unicodedata.normalize("NFD", word))
        assert OnboardingParser.email(word) is None

    @pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
    def test_unlink_phrase_survives_keyboard_forms(self, language: Language) -> None:
        """Составные буквы, регистр и лишние пробелы не отменяют подтверждения."""
        phrase = CATALOGS[language]["table_unlink.phrase"]
        typed = f"  {unicodedata.normalize('NFD', phrase).lower()} "
        assert _same_phrase(typed, phrase)
        assert not _same_phrase("да", phrase)

    @pytest.mark.parametrize(
        "language", [language for language in SUPPORTED_LANGUAGES if language is not Language.RU]
    )
    def test_no_cyrillic_outside_russian(self, language: Language) -> None:
        """Непереведённая строка выдаёт себя кириллицей."""
        cyrillic = re.compile("[А-Яа-яЁё]")
        assert [key for key, value in CATALOGS[language].items() if cyrillic.search(value)] == []
