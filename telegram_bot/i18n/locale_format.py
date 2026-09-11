"""Числа и даты по правилам языка обращения.

Разделители разрядов и дробной части, порядок дня и месяца — всё берётся из
CLDR через Babel, а не задаётся руками по языку: у хинди, например, разряды
группируются лакхами (`12,34,567.50`), и таблица «разделитель на язык» этого
бы не выразила.

Одно правило поверх CLDR сохранено от прежней печати: разряды разделяются
обычным пробелом. CLDR ставит там неразрывный или узкий неразрывный (русский,
французский), а их разные клиенты Telegram рисуют по-разному, и в журнале их
не найти поиском.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from functools import cache

from babel import Locale
from babel.dates import format_skeleton
from babel.numbers import format_decimal

from telegram_bot.i18n.context import current_language

#: Неразрывные пробелы CLDR → обычный пробел.
_PLAIN_SPACES = str.maketrans({"\u00a0": " ", "\u202f": " "})


@cache
def _locale(code: str) -> Locale:
    """Локаль Babel по коду языка."""
    return Locale.parse(code)


@cache
def _integer_pattern(code: str) -> str:
    """Целая часть десятичного шаблона языка: `#,##0` или `#,##,##0`."""
    pattern = _locale(code).decimal_formats[None].pattern
    return pattern.split(";")[0].split(".")[0]


def _plain(text: str) -> str:
    """Заменяет неразрывные пробелы обычными."""
    return text.translate(_PLAIN_SPACES)


class LocaleFormat:
    """Печать чисел и дат на языке текущего обращения."""

    @staticmethod
    def decimal(value: Decimal, places: int) -> str:
        """Число с разделением разрядов и ровно `places` знаками после запятой."""
        code = current_language().code
        pattern = _integer_pattern(code) + ("." + "0" * places if places else "")
        return _plain(format_decimal(value, format=pattern, locale=_locale(code)))

    @classmethod
    def integer(cls, value: int) -> str:
        """Целое с разделением разрядов."""
        return cls.decimal(Decimal(value), 0)

    @staticmethod
    def day(value: date) -> str:
        """Дата цифрами: `01.07.2026`, `7/1/2026`, …"""
        return _plain(format_skeleton("yMd", value, locale=_locale(current_language().code)))

    @staticmethod
    def moment(value: datetime) -> str:
        """Дата и время в 24-часовом формате: `25.07.2026 15:07`."""
        locale = _locale(current_language().code)
        return _plain(
            f"{format_skeleton('yMd', value, locale=locale)} "
            f"{format_skeleton('Hm', value, locale=locale)}"
        )
