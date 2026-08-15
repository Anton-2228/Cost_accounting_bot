"""Тесты разбора суммы.

Предмет проверки — денежная точность и внятность отказа. Старая версия
принимала сумму как `float` в валидации и приводила к `int` в команде: перевод
на «12.5» падал `ValueError` мимо всех обработчиков, и пользователь не получал
ничего.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from telegram_bot.parsers import AmountParser, ParseError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("500", Decimal("500")),
        ("12.5", Decimal("12.5")),
        ("12,5", Decimal("12,5".replace(",", "."))),
        ("  99.99  ", Decimal("99.99")),
        ("0.01", Decimal("0.01")),
    ],
)
def test_valid_amounts(raw: str, expected: Decimal) -> None:
    """Точка и запятая равноправны, пробелы по краям не мешают."""
    assert AmountParser.parse(raw) == expected


def test_result_is_decimal_not_float() -> None:
    """Тип обязан быть `Decimal`: через `float` копейки поплыли бы.

    `0.1 + 0.2` во float даёт 0.30000000000000004; вся система от этого
    избавлена, и разбор ввода — первое место, где это можно было бы сломать.
    """
    parsed = AmountParser.parse("1000.10")
    assert isinstance(parsed, Decimal)
    assert parsed + Decimal("0.20") == Decimal("1000.30")


@pytest.mark.parametrize("raw", ["0", "-5", "-0.01"])
def test_non_positive_is_rejected(raw: str) -> None:
    """Ноль и минус не принимаются: знак определяет категория, а не ввод."""
    with pytest.raises(ParseError, match="больше нуля"):
        AmountParser.parse(raw)


@pytest.mark.parametrize("raw", ["", "  ", "абв", "12абв", "1..2", "NaN", "Infinity"])
def test_garbage_is_rejected(raw: str) -> None:
    """Нечисловой ввод объясняется, а не роняет обработчик."""
    with pytest.raises(ParseError):
        AmountParser.parse(raw)


def test_too_many_decimal_places() -> None:
    """Больше двух знаков api отверг бы 422 без внятного текста."""
    with pytest.raises(ParseError, match="двух знаков"):
        AmountParser.parse("10.123")


def test_too_large_amount() -> None:
    """Сумма, не помещающаяся в NUMERIC(14, 2), отсекается до запроса."""
    with pytest.raises(ParseError, match="слишком большая"):
        AmountParser.parse("99999999999999")
