"""Тесты извлечения позиций из сырья чека.

Таблица примеров, а не проверка глазами: извлечение — чистая функция, и именно
на ней сосредоточены ошибки, из-за которых ветка чеков не работала в старой
версии (`float` вместо `Decimal`, чтение не того поля, `KeyError` мимо
обработчика).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from telegram_bot.checks import (
    ReceiptExtractor,
    ReceiptFormatError,
    ReceiptMismatchError,
    ReceiptNotSupportedError,
)

_QR = "t=20260725T1507&s=129.90&fn=7384440901402798&i=145&fp=698610272&n=1"


def _payload(**body: Any) -> dict[str, Any]:
    """Ответ внешнего сервиса с подставленным содержимым чека."""
    return {"code": 1, "data": {"json": body}}


def test_items_and_total_are_decimal_rubles() -> None:
    """Копейки превращаются в рубли ровно один раз и только `Decimal`.

    Старая версия делала `product["sum"] / 100` и получала `float`, нарушая
    инвариант «деньги — `Decimal`» в самой первой точке пути.
    """
    receipt = ReceiptExtractor.extract(
        _payload(
            operationType=1,
            totalSum=12990,
            retailPlace="Пятёрочка",
            items=[{"name": "молоко", "sum": 8990}, {"name": "хлеб", "sum": 4000}],
        ),
        _QR,
    )

    assert [item.amount for item in receipt.items] == [Decimal("89.90"), Decimal("40.00")]
    assert all(isinstance(item.amount, Decimal) for item in receipt.items)
    assert receipt.total == Decimal("129.90")
    assert receipt.retail_place == "Пятёрочка"


def test_zero_priced_item_survives() -> None:
    """Нулевая позиция остаётся в списке.

    Отбросить её значило бы разойтись с итогом чека — то есть сломать саму
    проверку, которой разбор себя контролирует.
    """
    receipt = ReceiptExtractor.extract(
        _payload(
            totalSum=8990,
            items=[{"name": "молоко", "sum": 8990}, {"name": "второе в подарок", "sum": 0}],
        ),
        _QR,
    )

    assert [item.amount for item in receipt.items] == [Decimal("89.90"), Decimal("0.00")]


def test_return_receipt_is_refused() -> None:
    """Возврат разбирать нечем: у него другой знак и другой смысл."""
    with pytest.raises(ReceiptNotSupportedError):
        ReceiptExtractor.extract(
            _payload(operationType=2, totalSum=8990, items=[{"name": "молоко", "sum": 8990}]),
            _QR,
        )


def test_total_mismatch_is_refused() -> None:
    """Расхождение с итогом — отказ, а не запись «примерно того же».

    Канарейка на «прочитали не то поле»: возьми разбор `price` вместо `sum`,
    расхождение вылезло бы здесь, а не в отчёте через месяц.
    """
    with pytest.raises(ReceiptMismatchError):
        ReceiptExtractor.extract(
            _payload(totalSum=12990, items=[{"name": "молоко", "sum": 8990}]),
            _QR,
        )


def test_missing_items_is_readable_error() -> None:
    """Расшифровка неожиданной формы даёт внятный отказ, а не `KeyError`."""
    with pytest.raises(ReceiptFormatError):
        ReceiptExtractor.extract(_payload(totalSum=8990), _QR)

    with pytest.raises(ReceiptFormatError):
        ReceiptExtractor.extract({"code": 1}, _QR)


def test_fractional_sum_is_refused() -> None:
    """Дробная сумма означает рубли там, где мы ждём копейки.

    Молча округлить значило бы записать сумму в сто раз меньше настоящей.
    """
    with pytest.raises(ReceiptFormatError):
        ReceiptExtractor.extract(
            _payload(totalSum=8990, items=[{"name": "молоко", "sum": 89.90}]),
            _QR,
        )


def test_total_falls_back_to_qr_field() -> None:
    """Без `totalSum` итог берётся из поля `s` QR-строки — в рублях."""
    receipt = ReceiptExtractor.extract(
        _payload(items=[{"name": "молоко", "sum": 8990}, {"name": "хлеб", "sum": 4000}]),
        _QR,
    )
    assert receipt.total == Decimal("129.90")


def test_purchase_time_falls_back_to_qr_field() -> None:
    """Без `dateTime` время покупки берётся из поля `t`.

    Вариант формата без секунд проверяется первым: `strptime` разрешает полям
    быть короче двух цифр, и `20260725T1507` по шаблону с секундами разобрался
    бы как 15:00:07 — молча и правдоподобно.
    """
    receipt = ReceiptExtractor.extract(
        _payload(totalSum=8990, items=[{"name": "молоко", "sum": 8990}]),
        "t=20260725T1507&s=89.90&fn=1&i=1&fp=1",
    )
    assert receipt.purchased_at == datetime(2026, 7, 25, 15, 7)


def test_nameless_item_gets_placeholder() -> None:
    """Позиция без названия не теряется: её сумма настоящая."""
    receipt = ReceiptExtractor.extract(
        _payload(totalSum=8990, items=[{"sum": 8990}]),
        _QR,
    )
    assert receipt.items[0].name
