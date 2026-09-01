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

from telegram_bot.api_client.models import Check, CheckKind, Currency
from telegram_bot.checks import (
    ReceiptExtractor,
    ReceiptFormatError,
    ReceiptMismatchError,
    ReceiptNotSupportedError,
)

_QR = "t=20260725T1507&s=129.90&fn=7384440901402798&i=145&fp=698610272&n=1"

_FETCHED_AT = datetime(2026, 7, 25, 15, 10)


def _check(
    raw_payload: dict[str, Any],
    *,
    kind: CheckKind = CheckKind.RU_FNS,
    qr_raw: str = _QR,
) -> Check:
    """Сохранённый чек: разбор выбирает разборщик по его виду."""
    return Check(id=1, kind=kind, qr_raw=qr_raw, raw_payload=raw_payload, fetched_at=_FETCHED_AT)


def _payload(**body: Any) -> dict[str, Any]:
    """Ответ внешнего сервиса с подставленным содержимым чека ФНС."""
    return {"code": 1, "data": {"json": body}}


def test_items_and_total_are_decimal_rubles() -> None:
    """Копейки превращаются в рубли ровно один раз и только `Decimal`.

    Старая версия делала `product["sum"] / 100` и получала `float`, нарушая
    инвариант «деньги — `Decimal`» в самой первой точке пути.
    """
    receipt = ReceiptExtractor.extract(
        _check(_payload(
            operationType=1,
            totalSum=12990,
            retailPlace="Пятёрочка",
            items=[{"name": "молоко", "sum": 8990}, {"name": "хлеб", "sum": 4000}],
        ))
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
        _check(_payload(
            totalSum=8990,
            items=[{"name": "молоко", "sum": 8990}, {"name": "второе в подарок", "sum": 0}],
        ))
    )

    assert [item.amount for item in receipt.items] == [Decimal("89.90"), Decimal("0.00")]


def test_return_receipt_is_refused() -> None:
    """Возврат разбирать нечем: у него другой знак и другой смысл."""
    with pytest.raises(ReceiptNotSupportedError):
        ReceiptExtractor.extract(
            _check(
                _payload(
                    operationType=2,
                    totalSum=8990,
                    items=[{"name": "молоко", "sum": 8990}],
                )
            )
        )


def test_total_mismatch_is_refused() -> None:
    """Расхождение с итогом — отказ, а не запись «примерно того же».

    Канарейка на «прочитали не то поле»: возьми разбор `price` вместо `sum`,
    расхождение вылезло бы здесь, а не в отчёте через месяц.
    """
    with pytest.raises(ReceiptMismatchError):
        ReceiptExtractor.extract(
            _check(_payload(totalSum=12990, items=[{"name": "молоко", "sum": 8990}]))
        )


def test_missing_items_is_readable_error() -> None:
    """Расшифровка неожиданной формы даёт внятный отказ, а не `KeyError`."""
    with pytest.raises(ReceiptFormatError):
        ReceiptExtractor.extract(_check(_payload(totalSum=8990)))

    with pytest.raises(ReceiptFormatError):
        ReceiptExtractor.extract(_check({"code": 1}))


def test_fractional_sum_is_refused() -> None:
    """Дробная сумма означает рубли там, где мы ждём копейки.

    Молча округлить значило бы записать сумму в сто раз меньше настоящей.
    """
    with pytest.raises(ReceiptFormatError):
        ReceiptExtractor.extract(
            _check(_payload(totalSum=8990, items=[{"name": "молоко", "sum": 89.90}]))
        )


def test_total_falls_back_to_qr_field() -> None:
    """Без `totalSum` итог берётся из поля `s` QR-строки — в рублях."""
    receipt = ReceiptExtractor.extract(
        _check(_payload(items=[{"name": "молоко", "sum": 8990}, {"name": "хлеб", "sum": 4000}]))
    )
    assert receipt.total == Decimal("129.90")


def test_purchase_time_falls_back_to_qr_field() -> None:
    """Без `dateTime` время покупки берётся из поля `t`.

    Вариант формата без секунд проверяется первым: `strptime` разрешает полям
    быть короче двух цифр, и `20260725T1507` по шаблону с секундами разобрался
    бы как 15:00:07 — молча и правдоподобно.
    """
    receipt = ReceiptExtractor.extract(
        _check(
            _payload(totalSum=8990, items=[{"name": "молоко", "sum": 8990}]),
            qr_raw="t=20260725T1507&s=89.90&fn=1&i=1&fp=1",
        )
    )
    assert receipt.purchased_at == datetime(2026, 7, 25, 15, 7)


def test_nameless_item_gets_placeholder() -> None:
    """Позиция без названия не теряется: её сумма настоящая."""
    receipt = ReceiptExtractor.extract(
        _check(_payload(totalSum=8990, items=[{"sum": 8990}]))
    )
    assert receipt.items[0].name


def test_ru_receipt_currency_comes_from_the_format() -> None:
    """Валюта берётся из формата чека, а не спрашивается и не угадывается."""
    receipt = ReceiptExtractor.extract(
        _check(_payload(totalSum=8990, items=[{"name": "молоко", "sum": 8990}]))
    )
    assert receipt.currency is Currency.RUB


# ---- Сербский чек ----


def _srb(**overrides: Any) -> dict[str, Any]:
    """Сербское сырьё: две версии, суммы строками — как их кладёт приём."""
    body: dict[str, Any] = {
        "Врста": "Промет",
        "Име продајног места": "1002342-195 - Maxi",
        "Предузеће": "DELHAIZE SERBIA DOO BEOGRAD",
        "Укупан износ": "610.38",
        "ПФР време (временска зона сервера)": "27.8.2026. 15:00:00",
        "Спецификација рачуна": [
            {"Назив": "Banana/KG", "Укупна цена": "93.43"},
            {"Назив": "Min.voda NG Rosa Sport 0.75l/KOM", "Укупна цена": "70.99"},
            {"Назив": "Monte 100g/KOM", "Укупна цена": "185.98"},
            {"Назив": "Kasika bambus Maxi 10 1/KOM", "Укупна цена": "109.99"},
            {"Назив": "Coffe Almond Imlek Nera 230ml/KOM", "Укупна цена": "149.99"},
        ],
    }
    body.update(overrides)
    return {"url": "https://suf.purs.gov.rs/v/?vl=…", "sr": body, "en": {}}


def _srb_check(raw_payload: dict[str, Any]) -> Check:
    """Сербский чек: разбор выбирается по виду, а не по содержимому."""
    return _check(raw_payload, kind=CheckKind.SRB_SUF, qr_raw=raw_payload["url"])


def test_srb_items_and_total_are_decimal_dinars() -> None:
    """Суммы читаются строками и остаются `Decimal`.

    Приём кладёт их строками именно затем, чтобы здесь не понадобился `float`:
    `Decimal("0.584")` — это 0.584, а `Decimal(0.584)` — нет.
    """
    receipt = ReceiptExtractor.extract(_srb_check(_srb()))

    assert [item.amount for item in receipt.items] == [
        Decimal("93.43"),
        Decimal("70.99"),
        Decimal("185.98"),
        Decimal("109.99"),
        Decimal("149.99"),
    ]
    assert all(isinstance(item.amount, Decimal) for item in receipt.items)
    assert receipt.total == Decimal("610.38")
    assert receipt.items[0].name == "Banana/KG"


def test_srb_currency_is_dinar() -> None:
    """Динар — свойство формата, а не выбор пользователя."""
    assert ReceiptExtractor.extract(_srb_check(_srb())).currency is Currency.RSD


def test_srb_shop_name_is_preferred_over_company() -> None:
    """Магазин говорит покупателю больше, чем юрлицо, под которым он работает."""
    receipt = ReceiptExtractor.extract(_srb_check(_srb()))
    assert receipt.retail_place == "1002342-195 - Maxi"

    without_shop = _srb()
    del without_shop["sr"]["Име продајног места"]
    fallback = ReceiptExtractor.extract(_srb_check(without_shop))
    assert fallback.retail_place == "DELHAIZE SERBIA DOO BEOGRAD"


def test_srb_purchase_time_is_read_without_leading_zeroes() -> None:
    """День и месяц на странице без ведущих нулей — «27.8.2026.», не «27.08»."""
    receipt = ReceiptExtractor.extract(_srb_check(_srb()))
    assert receipt.purchased_at == datetime(2026, 8, 27, 15, 0, 0)


def test_srb_refund_is_refused() -> None:
    """Возврат не покупка: записать его как покупку значило бы удвоить расход."""
    with pytest.raises(ReceiptNotSupportedError):
        ReceiptExtractor.extract(_srb_check(_srb(**{"Врста": "Рефундација"})))


def test_srb_total_mismatch_is_refused() -> None:
    """Расхождение с итогом — отказ. Та же канарейка, что и у ФНС."""
    with pytest.raises(ReceiptMismatchError):
        ReceiptExtractor.extract(_srb_check(_srb(**{"Укупан износ": "610.39"})))


def test_srb_zero_priced_item_survives() -> None:
    """Нулевая позиция остаётся: «второй товар в подарок» — законный чек."""
    payload = _srb()
    payload["sr"]["Спецификација рачуна"].append({"Назив": "Подарок", "Укупна цена": "0"})
    receipt = ReceiptExtractor.extract(_srb_check(payload))
    assert receipt.items[-1].amount == Decimal("0")


@pytest.mark.parametrize(
    "broken",
    [
        {"en": {}},
        {"sr": {"Укупан износ": "610.38"}},
        {"sr": {"Спецификација рачуна": [{"Назив": "Banana", "Укупна цена": "1"}]}},
        {"sr": {"Укупан износ": "много", "Спецификација рачуна": [{"Укупна цена": "1"}]}},
    ],
    ids=["нет сербской версии", "нет позиций", "нет итога", "итог не число"],
)
def test_srb_broken_payload_is_a_readable_refusal(broken: dict[str, Any]) -> None:
    """Сырьё неожиданной формы даёт внятный отказ, а не `KeyError`."""
    with pytest.raises(ReceiptFormatError):
        ReceiptExtractor.extract(_srb_check({"url": "https://suf.purs.gov.rs/v/?vl=…", **broken}))
