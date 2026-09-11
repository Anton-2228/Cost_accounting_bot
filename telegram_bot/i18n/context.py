"""Язык текущего обращения.

Язык едет в `ContextVar`, а не параметром: текст собирают десятки мест — от
команд до разбора ввода и печати сумм, — и протаскивать язык через каждое
значило бы переписать все их подписи ради одного значения, которое на время
обращения одно и то же.

`ContextVar` при этом не глобальная переменная: asyncio копирует контекст в
каждую задачу, и два пользователя, пишущие боту одновременно, своих языков не
перепутают.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from telegram_bot.i18n import language as _language
from telegram_bot.i18n.language import Language

_CURRENT: ContextVar[Language | None] = ContextVar("language", default=None)


def current_language() -> Language:
    """Язык текущего обращения; вне обращения — язык по умолчанию."""
    return _CURRENT.get() or _language.DEFAULT_LANGUAGE


@contextmanager
def language_scope(language: Language) -> Iterator[None]:
    """Выполняет блок на указанном языке и возвращает прежний на выходе.

    Выход через `reset`, а не повторный `set`: вложенная область (смена языка
    посреди обращения) обязана вернуть ровно то, что было снаружи, а не
    умолчание.
    """
    token = _CURRENT.set(language)
    try:
        yield
    finally:
        _CURRENT.reset(token)
