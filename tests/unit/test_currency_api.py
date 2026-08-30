"""Тесты разбора ответа источника курсов.

Проверяется чистая функция: ни сети, ни клиента. Пример взят с настоящей
раздачи — `.../@2024-08-20/v1/currencies/eur.json`, — но урезан до валют, о
которых знает перечисление, плюс пара посторонних.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from api.enums import Currency
from api.rates.base import RateUnavailableError
from api.rates.currency_api import parse_rates

_PAYLOAD = {
    "date": "2024-08-20",
    "eur": {
        "usd": 1.10867303,
        "rub": 100.17726765,
        "rsd": 117.05258573,
        "jpy": 161.94,
        "eur": 1,
    },
}


def test_known_currencies_are_extracted() -> None:
    """Из трёхсот валют берутся те, что перечисление умеет назвать."""
    assert parse_rates(_PAYLOAD, Currency.EUR) == {
        Currency.USD: Decimal("1.10867303"),
        Currency.RUB: Decimal("100.17726765"),
        Currency.RSD: Decimal("117.05258573"),
    }


def test_base_currency_is_not_in_the_result() -> None:
    """Курс к самому себе отбрасывается: в кэше его нет и быть не должно."""
    assert Currency.EUR not in parse_rates(_PAYLOAD, Currency.EUR)


def test_numbers_do_not_go_through_float() -> None:
    """Курс переводится в `Decimal` через строку, без двоичного хвоста.

    `Decimal(0.0085)` даёт число с хвостом из двоичного мусора, который затем
    честно ложится в `NUMERIC(24, 12)` и делает два пересчёта одной суммы
    неодинаковыми.
    """
    parsed = parse_rates({"rsd": {"eur": 0.008532621}}, Currency.RSD)
    assert parsed[Currency.EUR] == Decimal("0.008532621")


def test_string_rates_are_accepted() -> None:
    """Курс строкой разбирается так же: источник вправе менять представление."""
    parsed = parse_rates({"rsd": {"eur": "0.0085"}}, Currency.RSD)
    assert parsed[Currency.EUR] == Decimal("0.0085")


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="не объект"),
        pytest.param({"date": "2024-08-20"}, id="без базовой валюты"),
        pytest.param({"eur": "не словарь"}, id="котировки не объект"),
    ],
)
def test_unexpected_shape_is_refused(payload: object) -> None:
    """Неожиданная структура — отказ, а не пустой словарь.

    Пустой словарь означал бы «курсов нет», подсчёт продолжился бы без них и
    выдал бы неверное число вместо ошибки.
    """
    with pytest.raises(RateUnavailableError):
        parse_rates(payload, Currency.EUR)


def test_answer_without_any_known_currency_is_refused() -> None:
    """Ответ, в котором нет ни одной нашей валюты, бесполезен и отвергается."""
    with pytest.raises(RateUnavailableError):
        parse_rates({"eur": {"jpy": 161.94}}, Currency.EUR)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("не число", id="нечисловое"),
        pytest.param(0, id="ноль"),
        pytest.param(-1.5, id="отрицательное"),
    ],
)
def test_broken_quote_is_dropped_not_stored(value: object) -> None:
    """Испорченная котировка выбрасывается, а не едет в кэш.

    Ноль обнулил бы каждую операцию в этой валюте, отрицательный курс —
    перевернул бы её знак; и то и другое выглядело бы как настоящее число.
    Пропажу поймает вызывающий: недостающая котировка — отказ, см.
    `ExchangeRateService.ensure`.
    """
    parsed = parse_rates({"eur": {"usd": 1.1, "rub": value}}, Currency.EUR)
    assert parsed == {Currency.USD: Decimal("1.1")}
