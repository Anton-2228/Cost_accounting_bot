"""Печать денежных сумм."""

from __future__ import annotations

from decimal import Decimal

#: Разделитель разрядов. Обычный пробел, а не тонкий и не неразрывный: узкие
#: пробелы разные клиенты Telegram рисуют по-разному, а в журнале их не найти
#: поиском.
_GROUP_SEPARATOR = " "


class MoneyFormatter:
    """Приводит `Decimal` к виду «1 234,56 ₽».

    Знак снимается: направление операции пользователь видит по названию
    категории, а «-500» рядом со словом «расход» читается как двойное отрицание.
    Округления здесь нет — суммы приходят из api уже с двумя знаками, и любое
    приведение к `float` по дороге сделало бы копейки приблизительными.
    """

    @staticmethod
    def format(amount: Decimal) -> str:
        """Сумма с разделением разрядов, запятой и знаком рубля."""
        quantized = abs(amount).quantize(Decimal("0.01"))
        whole, _, fraction = f"{quantized:f}".partition(".")
        grouped = f"{int(whole):,}".replace(",", _GROUP_SEPARATOR)
        return f"{grouped},{fraction} ₽"
