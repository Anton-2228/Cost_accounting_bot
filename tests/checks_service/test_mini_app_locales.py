"""Тесты текстов Mini App.

Страница — статика без сборки, и проверить её каталог иначе как отсюда нечем:
забытый в одном языке ключ страница покажет пустой строкой, а забытый код
ошибки — общей фразой вместо объяснения.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from checks_service.enums import CheckKind
from checks_service.exceptions import ChecksError

_MINI_APP = Path(__file__).resolve().parents[2] / "mini_app"

#: Языки бота. Список здесь, а не из пакета бота: тестам сервиса незачем
#: поднимать его окружение ради пяти кодов.
_LANGUAGES = {"ru", "en", "hi", "es", "fr"}


def _locales() -> dict[str, dict[str, Any]]:
    """Каталоги из `locales.js`: после присваивания там — чистый JSON."""
    source = (_MINI_APP / "locales.js").read_text(encoding="utf-8")
    _, _, body = source.partition("window.MINI_APP_LOCALES = ")
    return dict(json.loads(body.strip().rstrip(";")))


def _shape(value: Any) -> Any:
    """Скелет каталога: ключи без значений."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return None


def _leaves(value: Any) -> list[Any]:
    """Все значения каталога."""
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    return [value]


def _error_codes() -> set[str]:
    """Коды всех отказов, которые сервис может вернуть странице."""
    codes: set[str] = set()
    pending: list[type[ChecksError]] = [ChecksError]
    while pending:
        current = pending.pop()
        pending.extend(current.__subclasses__())
        if current is not ChecksError:
            codes.add(current.code)
    return codes


def test_languages_are_those_of_the_bot() -> None:
    """Страница говорит на тех же языках, что и бот."""
    assert set(_locales()) == _LANGUAGES


@pytest.mark.parametrize("language", sorted(_LANGUAGES))
def test_same_keys_everywhere(language: str) -> None:
    """Ключ, забытый в переводе, страница показала бы пустым местом."""
    locales = _locales()
    assert _shape(locales[language]) == _shape(locales["en"])


@pytest.mark.parametrize("language", sorted(_LANGUAGES))
def test_no_empty_texts(language: str) -> None:
    """Пустая строка на экране хуже любой формулировки."""
    assert all(isinstance(leaf, str) and leaf.strip() for leaf in _leaves(_locales()[language]))


@pytest.mark.parametrize("language", sorted(_LANGUAGES))
def test_every_error_code_has_a_text(language: str) -> None:
    """Каждый отказ сервиса объясняется своими словами, а не общей фразой."""
    assert sorted(_error_codes() - set(_locales()[language]["errors"])) == []


@pytest.mark.parametrize("language", sorted(_LANGUAGES))
def test_every_check_kind_has_a_currency_sign(language: str) -> None:
    """Сумма чека любого формата подписывается своей валютой."""
    assert {kind.value for kind in CheckKind} <= set(_locales()[language]["currency"])


def test_every_page_key_exists() -> None:
    """Каждый `data-i18n` страницы есть в каталоге."""
    page = (_MINI_APP / "index.html").read_text(encoding="utf-8")
    keys = set(re.findall(r'data-i18n="([^"]+)"', page))
    assert keys
    for language, texts in _locales().items():
        assert sorted(keys - set(texts)) == [], language
