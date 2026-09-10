"""Результаты разбора пользовательского ввода.

Разбор возвращает модель, а не пару «значение или строка ошибки»: у команды
тогда остаётся ровно одна развилка, а текст ошибки нельзя случайно принять за
успешный результат. Старая версия использовала одновременно два несовместимых
протокола — pydantic-модель в одном месте и словарь
`{"status": "success"|"error"}` в другом.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from telegram_bot.api_client.models import Currency


class ParsedRecord(BaseModel):
    """Разобранная строка добавления операции."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: Currency
    category_id: int
    category_title: str
    category_is_income: bool
    notes: str


class ParsedCheckEdit(BaseModel):
    """Одна правка разбора чека: «1,3 - молочка».

    `numbers` — номера позиций так, как их видит пользователь: с единицы и в
    том же порядке, в каком напечатан список. Перевод в индексы делает команда,
    и делает его в одном месте.
    """

    model_config = ConfigDict(frozen=True)

    numbers: tuple[int, ...]
    value: str


class ParseError(Exception):
    """Ввод разобрать не удалось; текст уже готов для пользователя.

    Исключение, а не возвращаемое значение: разбор идёт по шагам (валюта,
    сумма, категория), и каждый шаг иначе пришлось бы оборачивать проверкой
    результата предыдущего.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


