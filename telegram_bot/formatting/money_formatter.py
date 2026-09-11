"""Печать денежных сумм."""

from __future__ import annotations

from decimal import Decimal

from telegram_bot.api_client.models import Currency
from telegram_bot.i18n import LocaleFormat, t


class MoneyFormatter:
    """Приводит `Decimal` к виду «1 234,56 ₽» по правилам языка обращения.

    Знак снимается: направление операции пользователь видит по названию
    категории, а «-500» рядом со словом «расход» читается как двойное отрицание.
    Округления здесь нет — суммы приходят из api уже с двумя знаками, и любое
    приведение к `float` по дороге сделало бы копейки приблизительными.

    Валюта обязательна и не имеет значения по умолчанию. Прежде рубль был зашит
    в саму функцию, и с появлением второй валюты умолчание печатало бы «₽»
    рядом с суммой в евро — то есть врало бы ровно там, где подпись и нужна.

    Знак валюты берётся из каталога, а не из таблицы здесь: у динара
    общепринятого символа нет, и его сокращение своё в каждом языке — «дин.»
    узнаётся по-русски, «din.» — везде ещё.
    """

    @staticmethod
    def format(amount: Decimal, currency: Currency) -> str:
        """Сумма с разделением разрядов, двумя знаками дроби и знаком валюты."""
        quantized = abs(amount).quantize(Decimal("0.01"))
        return t(
            "format.money",
            amount=LocaleFormat.decimal(quantized, 2),
            sign=t(f"currency.sign.{currency.value}"),
        )
