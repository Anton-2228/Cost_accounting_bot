"""Тесты парсера QR-кода ФНС."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from checks_service.enums import CheckKind
from checks_service.exceptions import FormatNotSupportedError
from checks_service.formats.ru_fns.parser import RuFnsQrParser
from tests.checks_service.factories import RU_FNS_KEY, RU_FNS_QR

parser = RuFnsQrParser()


def test_valid_qr_is_parsed_into_credentials_and_key() -> None:
    """Реквизиты, ключ дедупликации и плашка берутся прямо из строки.

    Ни одного вызова модели: всё, что старая версия просила у LLM, лежит в
    QR-коде готовым.
    """
    parsed = parser.parse(RU_FNS_QR)

    assert parsed.kind is CheckKind.RU_FNS
    assert parsed.external_key == RU_FNS_KEY
    # `i` в QR-коде и `fd` в запросе расшифровки — одно и то же поле.
    assert parsed.credentials == {
        "fn": "7384440901402798",
        "fd": "145",
        "fp": "698610272",
        "t": "20260725T1507",
        "s": "1214.95",
    }
    assert parsed.preview.total == Decimal("1214.95")
    assert parsed.preview.purchased_at == datetime(2026, 7, 25, 15, 7)


def test_total_is_decimal_not_float() -> None:
    """Сумма десятичная: через float копейки терялись бы уже на плашке."""
    parsed = parser.parse("t=20260725T1507&s=0.10&fn=1&i=2&fp=3")
    assert parsed.preview.total == Decimal("0.10")
    # Ровно так float и врёт: Decimal(0.1) — это 0.1000000000000000055511151231…
    assert parsed.preview.total != Decimal(0.1)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        ("20260725T1507", datetime(2026, 7, 25, 15, 7)),
        ("20260725T150730", datetime(2026, 7, 25, 15, 7, 30)),
    ],
    ids=["без секунд", "с секундами"],
)
def test_both_time_formats_are_understood(moment: str, expected: datetime) -> None:
    """Секунды в поле `t` бывают и не бывают — читаются оба варианта.

    Проверяется именно время, а не только дата: `strptime` разрешает полям
    быть короче двух цифр, и по шаблону с секундами «1507» разбирается как
    15:00:07 — молча и правдоподобно.
    """
    parsed = parser.parse(f"t={moment}&s=10.00&fn=1&i=2&fp=3")
    assert parsed.preview.purchased_at == expected


@pytest.mark.parametrize(
    "qr",
    [
        "",
        "просто текст",
        "https://example.com/чек",
        # Сербский фискальный чек: другой формат, другой источник расшифровки.
        "https://suf.purs.gov.rs/v/?vl=A1ZQMDI4NTE5",
        # Реквизиты есть, но не все: без ФП чек не расшифровать.
        "t=20260725T1507&s=1214.95&fn=7384440901402798&i=145",
    ],
    ids=["пусто", "текст", "ссылка", "сербский чек", "без ФП"],
)
def test_foreign_strings_do_not_match(qr: str) -> None:
    """Чужая строка не выдаётся за чек ФНС.

    Это и есть точка расширения: сербский чек сегодня не подходит ни одному
    парсеру и получает честное «формат не поддерживается», а не разбор наугад.
    """
    assert parser.matches(qr) is False


def test_parse_of_incomplete_qr_names_missing_fields() -> None:
    """Разбор неполной строки называет недостающие реквизиты."""
    with pytest.raises(FormatNotSupportedError) as error:
        parser.parse("t=20260725T1507&s=1214.95&fn=7384440901402798")
    assert "i" in str(error.value)
    assert "fp" in str(error.value)


def test_key_distinguishes_two_checks_of_one_shop() -> None:
    """Два разных чека одной кассы дают разные ключи.

    Ключ составной именно поэтому: ФН у них общий, различает их номер
    документа.
    """
    first = parser.parse("t=20260725T1507&s=10.00&fn=738&i=145&fp=698")
    second = parser.parse("t=20260725T1509&s=20.00&fn=738&i=146&fp=699")
    assert first.external_key != second.external_key
