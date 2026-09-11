"""Каталоги текстов бота, по одному на язык.

Каталог языка — папка `resources/locales/<код>/`:

* `strings.toml` — короткие строки: кнопки, отказы разбора, подписи отчётов.
  Вложенные таблицы разворачиваются в ключи через точку: `[buttons.menu]` с
  полем `table` — это ключ `buttons.menu.table`;
* `*.txt` — длинные тексты, по файлу на сообщение. Ключ — `text.` и имя файла
  в нижнем регистре: `WELCOME.txt` — это `text.welcome`.

Всё читается один раз на импорте и падает сразу же, если что-то не так:
испорченный шаблон, найденный на старте, — ошибка сборки, а найденный на
сообщении пользователя — молчание в ответ.

`encoding="utf-8"` обязателен: файлы целиком нелатинские, а `read_text()` без
кодировки берёт локаль системы.
"""

from __future__ import annotations

import string
import tomllib
from pathlib import Path
from typing import Any

from telegram_bot.i18n.language import PICKER_ORDER, Language

#: Корень каталогов.
LOCALES_DIR = Path(__file__).resolve().parent.parent / "resources" / "locales"

#: Имя файла коротких строк в папке языка.
STRINGS_FILE = "strings.toml"

#: Префикс ключей длинных текстов.
TEXT_PREFIX = "text."


class CatalogError(Exception):
    """Каталог не читается: испорченный шаблон, повтор ключа, не строка."""


def placeholders(template: str) -> frozenset[str]:
    """Имена подстановок шаблона: `"Сумма {amount}"` → `{"amount"}`.

    Разбор тот же, что у `str.format`, поэтому шаблон, прошедший эту проверку,
    не упадёт на подстановке из-за незакрытой скобки.
    """
    try:
        return frozenset(
            field for _, field, _, _ in string.Formatter().parse(template) if field
        )
    except ValueError as error:
        raise CatalogError(f"Испорченный шаблон «{template}»: {error}") from error


def load_language(directory: Path) -> dict[str, str]:
    """Читает каталог одного языка в плоский словарь «ключ → шаблон»."""
    strings: dict[str, str] = {}
    with (directory / STRINGS_FILE).open("rb") as file:
        _flatten(tomllib.load(file), "", strings)

    for path in sorted(directory.glob("*.txt")):
        key = TEXT_PREFIX + path.stem.lower()
        if key in strings:
            raise CatalogError(f"Ключ «{key}» задан дважды в {directory}")
        strings[key] = path.read_text(encoding="utf-8").strip()

    for template in strings.values():
        placeholders(template)
    return strings


def load_all(root: Path = LOCALES_DIR) -> dict[Language, dict[str, str]]:
    """Каталоги всех языков, для которых есть папка."""
    return {
        language: load_language(root / language.code)
        for language in Language
        if (root / language.code).is_dir()
    }


def _flatten(table: dict[str, Any], prefix: str, into: dict[str, str]) -> None:
    """Разворачивает вложенные таблицы TOML в ключи через точку."""
    for name, value in table.items():
        key = f"{prefix}{name}"
        if isinstance(value, dict):
            _flatten(value, f"{key}.", into)
        elif isinstance(value, str):
            into[key] = value
        else:
            raise CatalogError(f"Ключ «{key}»: ожидалась строка, а не {type(value).__name__}")


CATALOGS: dict[Language, dict[str, str]] = load_all()

#: Языки, которые можно выбрать: те, у кого есть каталог, в порядке кнопок.
SUPPORTED_LANGUAGES: tuple[Language, ...] = tuple(
    language for language in PICKER_ORDER if language in CATALOGS
)
