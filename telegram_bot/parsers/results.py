"""Результаты разбора пользовательского ввода.

Разбор возвращает модель, а не пару «значение или строка ошибки»: у команды
тогда остаётся ровно одна развилка, а текст ошибки нельзя случайно принять за
успешный результат. Старая версия использовала одновременно два несовместимых
протокола — pydantic-модель в одном месте и словарь
`{"status": "success"|"error"}` в другом.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

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
    #: День, которым датировать операцию. `None` значит «пользователь дня не
    #: называл», и api поставит сегодняшний день документа; второго смысла у
    #: пустоты тут нет.
    added_at: date | None = None


class CheckEditKind(StrEnum):
    """Вид правки чека.

    Нужен ровно для одного: проверки «позиция указана дважды». Она считается по
    видам, а не по номерам вообще, потому что «1 - молочка» и «1-500» в одном
    сообщении друг другу не противоречат — это тип и цена одной позиции.
    """

    VALUE = "value"
    PRICE = "price"
    DELETE = "delete"


class ParsedCheckEdit(BaseModel):
    """Одна правка разбора чека: «1,3 - молочка», «1,3-500» или «!1,3».

    `numbers` — номера позиций так, как их видит пользователь: с единицы и в
    том же порядке, в каком напечатан список. Перевод в индексы делает команда,
    и делает его в одном месте.

    Одна модель на все три вида, а не три: в сообщении они перемешаны
    построчно, и проверка «позиция указана дважды» обязана видеть их в одном
    списке.
    """

    model_config = ConfigDict(frozen=True)

    numbers: tuple[int, ...]
    #: Пусто у строки удаления и у строки цены: назначается не текст.
    value: str = ""
    #: Новая цена позиции. Каждой из `numbers` — она же целиком, а не доля.
    amount: Decimal | None = None
    delete: bool = False

    @property
    def kind(self) -> CheckEditKind:
        """Вид правки — то, по чему считается конфликт в одном сообщении."""
        if self.delete:
            return CheckEditKind.DELETE
        if self.amount is not None:
            return CheckEditKind.PRICE
        return CheckEditKind.VALUE


class ParseError(Exception):
    """Ввод разобрать не удалось; текст уже готов для пользователя.

    Исключение, а не возвращаемое значение: разбор идёт по шагам (валюта,
    сумма, категория), и каждый шаг иначе пришлось бы оборачивать проверкой
    результата предыдущего.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


