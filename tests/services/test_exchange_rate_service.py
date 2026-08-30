"""Тесты дозагрузки курсов в кэш."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import Currency
from api.rates.base import RateUnavailableError
from api.repositories.exchange_rate_repository import ExchangeRateRepository
from api.services.exchange_rate_service import ExchangeRateService
from tests.fakes import BrokenRateProvider, FakeRateProvider

pytestmark = pytest.mark.usefixtures("clean_db")

_DAY = date(2026, 8, 20)
_NEXT_DAY = date(2026, 8, 21)


def _service(session: AsyncSession, provider: object) -> ExchangeRateService:
    """Сервис на фейковом источнике."""
    return ExchangeRateService(session, ExchangeRateRepository(session), provider)  # type: ignore[arg-type]


async def test_one_request_covers_every_quote_of_the_same_day(session: AsyncSession) -> None:
    """Два курса одной базы за один день стоят одного похода.

    Ответ источника содержит котировки ко всем валютам сразу, поэтому запросов
    столько, сколько различных пар «база + день», а не сколько курсов.
    """
    provider = FakeRateProvider()
    provider.add(
        Currency.RSD,
        _DAY,
        {Currency.EUR: Decimal("0.0085"), Currency.RUB: Decimal("0.87")},
    )

    await _service(session, provider).ensure(
        [
            (Currency.RSD, Currency.EUR, _DAY),
            (Currency.RSD, Currency.RUB, _DAY),
        ]
    )

    assert provider.calls == [(Currency.RSD, _DAY)]


async def test_whole_answer_is_stored_not_only_what_was_asked(session: AsyncSession) -> None:
    """В кэш ложится весь ответ, а не одна запрошенная котировка.

    Остальные уже получены и оплачены походом; выбросив их, следующий подсчёт по
    другой паре тех же валют пошёл бы в сеть за тем, что только что держал в
    руках.
    """
    provider = FakeRateProvider()
    provider.add(
        Currency.RSD,
        _DAY,
        {Currency.EUR: Decimal("0.0085"), Currency.USD: Decimal("0.0095")},
    )

    await _service(session, provider).ensure([(Currency.RSD, Currency.EUR, _DAY)])

    stored = await ExchangeRateRepository(session).existing(
        {(Currency.RSD, Currency.EUR, _DAY), (Currency.RSD, Currency.USD, _DAY)}
    )
    assert stored == {
        (Currency.RSD, Currency.EUR, _DAY),
        (Currency.RSD, Currency.USD, _DAY),
    }


async def test_cached_rate_is_not_fetched_again(session: AsyncSession) -> None:
    """Второй вызов не ходит в источник вовсе.

    Подсчёт остатка идёт при каждой перерисовке листа, то есть часто; поход в
    сеть за уже известным курсом был бы платой ни за что.
    """
    provider = FakeRateProvider()
    provider.add(Currency.RSD, _DAY, {Currency.EUR: Decimal("0.0085")})
    service = _service(session, provider)

    await service.ensure([(Currency.RSD, Currency.EUR, _DAY)])
    await service.ensure([(Currency.RSD, Currency.EUR, _DAY)])

    assert provider.calls == [(Currency.RSD, _DAY)]


async def test_only_the_missing_day_is_fetched(session: AsyncSession) -> None:
    """Из двух дней запрашивается тот, которого нет."""
    provider = FakeRateProvider()
    provider.add(Currency.RSD, _DAY, {Currency.EUR: Decimal("0.0085")})
    provider.add(Currency.RSD, _NEXT_DAY, {Currency.EUR: Decimal("0.0086")})
    service = _service(session, provider)

    await service.ensure([(Currency.RSD, Currency.EUR, _DAY)])
    provider.calls.clear()
    await service.ensure(
        [
            (Currency.RSD, Currency.EUR, _DAY),
            (Currency.RSD, Currency.EUR, _NEXT_DAY),
        ]
    )

    assert provider.calls == [(Currency.RSD, _NEXT_DAY)]


async def test_same_currency_is_never_requested(session: AsyncSession) -> None:
    """Курс валюты к себе самой не запрашивается: он единица и подставляется в SQL."""
    provider = FakeRateProvider()

    await _service(session, provider).ensure([(Currency.EUR, Currency.EUR, _DAY)])

    assert provider.calls == []


async def test_unavailable_source_is_propagated(session: AsyncSession) -> None:
    """Отказ источника выходит наружу, а не проглатывается.

    Проглоти его сервис — подсчёт пошёл бы дальше без части курсов и выдал бы
    правдоподобное неверное число. Ошибка доедет до задачи перерисовки, та
    повторится, а в таблице до тех пор останутся прежние верные значения.
    """
    with pytest.raises(RateUnavailableError):
        await _service(session, BrokenRateProvider()).ensure(
            [(Currency.RSD, Currency.EUR, _DAY)]
        )


async def test_partial_answer_is_a_failure_not_a_gap(session: AsyncSession) -> None:
    """Ответ без запрошенной котировки — отказ, а не молчаливый пропуск.

    Пропущенный курс не попал бы в кэш, агрегат получил бы на его месте `NULL`,
    и остаток занизился бы ровно на эту операцию. Из двух исходов — «ошибка» и
    «правдоподобное неверное число» — выбран первый.
    """
    provider = FakeRateProvider()
    provider.add(Currency.RSD, _DAY, {Currency.RUB: Decimal("0.87")})

    with pytest.raises(RateUnavailableError):
        await _service(session, provider).ensure([(Currency.RSD, Currency.EUR, _DAY)])
