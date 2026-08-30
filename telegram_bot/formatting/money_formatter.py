"""Печать денежных сумм."""

from __future__ import annotations

from decimal import Decimal

from telegram_bot.api_client.models import Currency

#: Разделитель разрядов. Обычный пробел, а не тонкий и не неразрывный: узкие
#: пробелы разные клиенты Telegram рисуют по-разному, а в журнале их не найти
#: поиском.
_GROUP_SEPARATOR = " "

#: Чем подписывается сумма. У динара своего общепринятого знака нет, поэтому
#: сокращение: «дин.» узнаётся, а выдуманный символ — нет.
_SIGNS: dict[Currency, str] = {
    Currency.RUB: "₽",
    Currency.USD: "$",
    Currency.EUR: "€",
    Currency.RSD: "дин.",
}


class MoneyFormatter:
    """Приводит `Decimal` к виду «1 234,56 ₽».

    Знак снимается: направление операции пользователь видит по названию
    категории, а «-500» рядом со словом «расход» читается как двойное отрицание.
    Округления здесь нет — суммы приходят из api уже с двумя знаками, и любое
    приведение к `float` по дороге сделало бы копейки приблизительными.

    Валюта обязательна и не имеет значения по умолчанию. Прежде рубль был зашит
    в саму функцию, и с появлением второй валюты умолчание печатало бы «₽»
    рядом с суммой в евро — то есть врало бы ровно там, где подпись и нужна.
    """

    @staticmethod
    def format(amount: Decimal, currency: Currency) -> str:
        """Сумма с разделением разрядов, запятой и знаком валюты."""
        quantized = abs(amount).quantize(Decimal("0.01"))
        whole, _, fraction = f"{quantized:f}".partition(".")
        grouped = f"{int(whole):,}".replace(",", _GROUP_SEPARATOR)
        return f"{grouped},{fraction} {_SIGNS[currency]}"
