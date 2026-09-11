"""Разбор денежной суммы."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from telegram_bot import constants
from telegram_bot.i18n import t
from telegram_bot.parsers.results import ParseError

_MAX_AMOUNT = Decimal("999999999999")


class AmountParser:
    """Превращает ввод пользователя в `Decimal`.

    Именно `Decimal`, а не `float`: сумма едет в api как строка и ложится в
    `NUMERIC(14, 2)`. Промежуточный `float` внёс бы в копейки двоичную
    погрешность там, где вся система от неё сознательно избавлена.

    Запятая принимается наравне с точкой: сумму набирают на телефоне, где под
    рукой запятая. Старая версия на «12,5» отвечала «Сумма должна быть числом»,
    а на «12.5» в переводе падала `ValueError` в тишину — валидация проверяла
    `float`, а команда затем делала `int`.
    """

    @classmethod
    def parse(cls, raw: str) -> Decimal:
        """Разбирает сумму или бросает :class:`ParseError` с готовым текстом."""
        normalized = raw.strip()
        for separator in constants.DECIMAL_SEPARATORS:
            normalized = normalized.replace(separator, ".")

        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            raise ParseError(t("parse.amount.invalid", raw=raw)) from None

        if not amount.is_finite():
            raise ParseError(t("parse.amount.invalid", raw=raw))
        if amount <= 0:
            raise ParseError(t("parse.amount.not_positive"))
        if amount > _MAX_AMOUNT:
            raise ParseError(t("parse.amount.too_big"))
        # `exponent` объявлен как int | Literal["n", "N", "F"]: буквенные
        # значения бывают только у NaN и бесконечности, а они отсеяны выше.
        exponent = amount.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > constants.MONEY_DECIMAL_PLACES:
            raise ParseError(t("parse.amount.too_precise"))
        return amount
