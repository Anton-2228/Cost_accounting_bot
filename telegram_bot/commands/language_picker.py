"""Клавиатура выбора языка: страницы, отметка текущего, навигация.

Чистая логика без aiogram и сети: раскладку проверяют тесты, а обе команды,
которым она нужна (`/start` и настройки), не импортируют друг друга.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from telegram_bot.enums import CommandName
from telegram_bot.i18n import NATIVE_LABELS, SUPPORTED_LANGUAGES, Language, t

#: Языков на одной странице.
PAGE_SIZE = 4

#: Откуда открыт выбор. Едет в `callback_data`: после выбора бот продолжает
#: там, откуда пришли, — приветствием после `/start`, экраном настроек после
#: настроек.
ORIGIN_START = "start"
ORIGIN_SETTINGS = "settings"
ORIGINS = frozenset({ORIGIN_START, ORIGIN_SETTINGS})

#: Действия кнопок. `noop` — у инертных кнопок навигации: номер страницы и
#: заглушка на краю. Telegram не даёт кнопке остаться без `callback_data`.
ACTION_OPEN = "open"
ACTION_PAGE = "page"
ACTION_SET = "set"
ACTION_NOOP = "noop"

#: `callback_data` кнопки «Назад» у выбора из настроек: экран настроек рисуется
#: на месте выбора. Та же кнопка, что «Настройки» в меню, — обе открывают экран
#: в нажатом сообщении.
BACK_DATA = f"{CommandName.SETTINGS}:open"

_PREFIX = CommandName.LANGUAGE
_PREVIOUS = "◀"
_NEXT = "▶"
#: Заглушка вместо стрелки на краю. Не пробел: пустую надпись Telegram не
#: принимает, а пробельную — рисует непредсказуемо.
_PLACEHOLDER = "·"
_CURRENT_MARK = "✓ "

#: Ряд клавиатуры: пары «надпись, `callback_data`».
Row = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PickerAction:
    """Разобранная `callback_data` кнопки выбора языка."""

    action: str
    origin: str | None = None
    value: str | None = None


def open_data() -> str:
    """`callback_data` кнопки «Язык» в настройках."""
    return f"{_PREFIX}:{ACTION_OPEN}"


def page_count(languages: Sequence[Language] = SUPPORTED_LANGUAGES) -> int:
    """Сколько страниц у выбора; хотя бы одна."""
    return max(1, -(-len(languages) // PAGE_SIZE))


def page_of(language: Language, languages: Sequence[Language] = SUPPORTED_LANGUAGES) -> int:
    """Страница, на которой стоит язык, с единицы.

    Выбор открывается на странице текущего языка: французу, листающему к
    своему языку каждый раз, отметка ✓ на первой странице ничего бы не дала.
    """
    if language not in languages:
        return 1
    return list(languages).index(language) // PAGE_SIZE + 1


def rows(
    *,
    origin: str,
    page: int,
    current: Language,
    languages: Sequence[Language] = SUPPORTED_LANGUAGES,
) -> list[Row]:
    """Клавиатура страницы: язык в ряд и ряд навигации под ними.

    Ряд навигации — `[◀][n/N][▶]`, на краях вместо стрелки инертная заглушка:
    ряд не меняет ширину от страницы к странице, и кнопки не прыгают под
    пальцем. Одна страница — навигации нет вовсе.

    У выбора из настроек последний ряд — «Назад» к ним; здесь, а не у команды,
    чтобы он не пропадал при листании. На `/start` возвращаться некуда.
    """
    total = page_count(languages)
    page = min(max(page, 1), total)
    chunk = languages[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]

    result: list[Row] = [
        (
            (
                (_CURRENT_MARK if language is current else "") + NATIVE_LABELS[language],
                f"{_PREFIX}:{ACTION_SET}:{origin}:{language.code}",
            ),
        )
        for language in chunk
    ]
    if total > 1:
        noop = f"{_PREFIX}:{ACTION_NOOP}"
        previous = (
            (_PREVIOUS, f"{_PREFIX}:{ACTION_PAGE}:{origin}:{page - 1}")
            if page > 1
            else (_PLACEHOLDER, noop)
        )
        following = (
            (_NEXT, f"{_PREFIX}:{ACTION_PAGE}:{origin}:{page + 1}")
            if page < total
            else (_PLACEHOLDER, noop)
        )
        result.append((previous, (f"{page}/{total}", noop), following))
    if origin == ORIGIN_SETTINGS:
        result.append(((t("buttons.back"), BACK_DATA),))
    return result


def parse(data: str | None) -> PickerAction | None:
    """Разбирает `callback_data`; `None` — это не кнопка выбора языка.

    Кнопка живёт в переписке дольше своей версии бота, поэтому незнакомая
    форма — не ошибка сборки, а повод промолчать.
    """
    parts = (data or "").split(":")
    if len(parts) < 2 or parts[0] != _PREFIX:
        return None
    action = parts[1]
    if action in {ACTION_OPEN, ACTION_NOOP} and len(parts) == 2:
        return PickerAction(action)
    if action in {ACTION_PAGE, ACTION_SET} and len(parts) == 4 and parts[2] in ORIGINS:
        return PickerAction(action, origin=parts[2], value=parts[3])
    return None
