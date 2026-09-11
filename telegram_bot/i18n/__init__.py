"""Язык интерфейса: каталоги текстов, язык обращения и подстановка по ключу.

Пользовательский текст в боте один на все языки только в виде ключа: сами
формулировки лежат в `resources/locales/<код>/`, а код зовёт :func:`t`. Язык
обращения выбирает `Manager` — один раз на входе, до команды.
"""

from __future__ import annotations

from telegram_bot.i18n.catalog import CATALOGS, SUPPORTED_LANGUAGES
from telegram_bot.i18n.context import current_language, language_scope
from telegram_bot.i18n.language import ENGLISH_NAMES, NATIVE_LABELS, PICKER_ORDER, Language
from telegram_bot.i18n.locale_format import LocaleFormat
from telegram_bot.i18n.translator import t, t_in

__all__ = [
    "CATALOGS",
    "ENGLISH_NAMES",
    "NATIVE_LABELS",
    "PICKER_ORDER",
    "SUPPORTED_LANGUAGES",
    "Language",
    "LocaleFormat",
    "current_language",
    "language_scope",
    "t",
    "t_in",
]
