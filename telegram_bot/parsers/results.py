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


class ParsedRecord(BaseModel):
    """Разобранная строка добавления операции."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    category_id: int
    category_title: str
    category_is_income: bool
    source_id: int
    source_title: str
    notes: str


class ParsedTransfer(BaseModel):
    """Разобранная строка перевода."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    from_source_id: int
    from_source_title: str
    to_source_id: int
    to_source_title: str
    notes: str


class ParseError(Exception):
    """Ввод разобрать не удалось; текст уже готов для пользователя.

    Исключение, а не возвращаемое значение: разбор идёт по шагам (сумма,
    категория, счёт), и каждый шаг иначе пришлось бы оборачивать проверкой
    результата предыдущего.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
