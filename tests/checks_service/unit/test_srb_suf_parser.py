"""Тесты парсера ссылки сербского чека."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from checks_service.enums import CheckKind
from checks_service.exceptions import FormatNotSupportedError
from checks_service.formats.srb_suf.parser import SrbSufQrParser
from tests.checks_service.factories import RU_FNS_QR, SRB_SUF_KEY, SRB_SUF_QR

parser = SrbSufQrParser()


def test_link_is_parsed_without_any_network_call() -> None:
    """Номер чека, сумма и время берутся из самой ссылки.

    Это главное свойство формата: плашка собирается до того, как мы сходили
    хоть куда-нибудь. Значения сверены с тем, что показывает сама страница
    чека — 610,38 динара, 27.08.2026 15:00 по Белграду (13:00 UTC).
    """
    parsed = parser.parse(SRB_SUF_QR)

    assert parsed.kind is CheckKind.SRB_SUF
    assert parsed.external_key == SRB_SUF_KEY
    assert parsed.credentials == {"url": SRB_SUF_QR, "invoice_number": SRB_SUF_KEY}
    assert parsed.preview.total == Decimal("610.38")
    assert parsed.preview.purchased_at == datetime(2026, 8, 27, 13, 0, 0, 108_000, tzinfo=UTC)


def test_total_is_decimal_not_float() -> None:
    """Сумма десятичная: через float пары терялись бы уже на плашке."""
    total = parser.parse(SRB_SUF_QR).preview.total
    assert isinstance(total, Decimal)
    # Ровно так float и врёт при делении на 10000.
    assert total == Decimal("610.38")


def test_qr_is_the_source_of_truth_for_the_fetcher() -> None:
    """Ссылка едет фетчеру целиком: страница чека и есть его источник."""
    assert parser.parse(f"  {SRB_SUF_QR}  ").qr_raw == SRB_SUF_QR


@pytest.mark.parametrize(
    "qr",
    [
        RU_FNS_QR,
        "https://suf.purs.gov.rs/v/?vl=",
        "https://suf.purs.gov.rs/v/",
        "https://mapr.tax.gov.me/v/?vl=A1lNUVFXR0tD",
        "http://suf.purs.gov.rs/v/?vl=A1lNUVFXR0tD",
        "https://suf.purs.gov.rs.evil.example/v/?vl=A1lNUVFXR0tD",
        "https://suf.purs.gov.rs/v/?vl=не-base64-вовсе",
        "Banana/KG",
        "",
    ],
    ids=[
        "чек ФНС",
        "пустой vl",
        "vl отсутствует",
        "чужой инстанс TaxCore",
        "http вместо https",
        "хост-двойник",
        "vl не декодируется",
        "штрихкод товара",
        "пустая строка",
    ],
)
def test_foreign_strings_are_not_matched(qr: str) -> None:
    """Ни одна чужая строка не признаётся сербским чеком.

    Хост-двойник тут не паранойя: сравнивай мы вхождением подстроки, любой
    домен, оканчивающийся на наш, увёл бы расшифровку на чужой сервер.
    """
    assert parser.matches(qr) is False


def test_truncated_payload_is_not_matched() -> None:
    """Короткий `vl` — не чек: заголовка в нём просто нет.

    Проверка живёт в `matches`, а не только в `parse`: реестр зовёт `parse`
    лишь после успешного `matches`, и такая строка обязана уйти в общий отказ
    «формат не распознан», а не свалиться исключением из середины разбора.
    """
    truncated = "https://suf.purs.gov.rs/v/?vl=A1lNUVFXR0tDWU1RUVdHS0M%3D"
    assert parser.matches(truncated) is False


def test_parse_of_unmatched_string_is_a_clean_refusal() -> None:
    """Даже позванный напрямую, `parse` отказывает внятно, а не падает."""
    with pytest.raises(FormatNotSupportedError):
        parser.parse("https://suf.purs.gov.rs/v/?vl=A1lN")


def test_matched_link_is_parseable() -> None:
    """`matches` и `parse` согласованы: что признано, то и разбирается."""
    assert parser.matches(SRB_SUF_QR) is True
    assert parser.parse(SRB_SUF_QR).external_key == SRB_SUF_KEY
