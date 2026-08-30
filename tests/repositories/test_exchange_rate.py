"""Тесты кэша курсов валют."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.exchange_rate import ExchangeRate
from api.enums import Currency
from api.orm.exchange_rate import ExchangeRateORM
from api.repositories.exchange_rate_repository import ExchangeRateRepository

pytestmark = pytest.mark.usefixtures("clean_db")

_DAY = date(2026, 8, 20)


def _rate(
    base: Currency = Currency.RSD,
    quote: Currency = Currency.EUR,
    rate: str = "0.008532",
    day: date = _DAY,
) -> ExchangeRate:
    """Строка кэша."""
    return ExchangeRate(
        base_currency=base,
        quote_currency=quote,
        rate_date=day,
        rate=Decimal(rate),
    )


async def test_repeated_write_of_the_same_day_changes_nothing(session: AsyncSession) -> None:
    """Повторная запись того же дня не перетирает курс и не падает.

    Курс за прошедший день — факт. Перезапись означала бы, что вчерашний остаток
    счёта сегодня стал другим, а конфликт здесь ожидаем: два подсчёта могут
    одновременно обнаружить нехватку одного и того же дня.
    """
    repository = ExchangeRateRepository(session)

    assert await repository.upsert_many([_rate(rate="0.008532")]) == 1
    assert await repository.upsert_many([_rate(rate="999")]) == 0
    await session.commit()

    stored = await session.get(ExchangeRateORM, 1)
    assert stored is not None
    assert stored.rate == Decimal("0.008532")


async def test_existing_reports_only_what_is_stored(session: AsyncSession) -> None:
    """Спрашивают тройкой «из, во, когда» — отвечают тем же."""
    repository = ExchangeRateRepository(session)
    await repository.upsert_many([_rate()])
    await session.commit()

    wanted = {
        (Currency.RSD, Currency.EUR, _DAY),
        (Currency.RSD, Currency.EUR, date(2026, 8, 21)),
        (Currency.USD, Currency.EUR, _DAY),
    }
    assert await repository.existing(wanted) == {(Currency.RSD, Currency.EUR, _DAY)}


async def test_empty_request_touches_nothing(session: AsyncSession) -> None:
    """Пустой список не превращается в запрос: подсчёт без конвертаций частый."""
    repository = ExchangeRateRepository(session)
    assert await repository.existing(set()) == set()
    assert await repository.upsert_many([]) == 0


async def test_opposite_direction_is_a_separate_row(session: AsyncSession) -> None:
    """RSD→EUR и EUR→RSD — разные строки, а не одна с обратным курсом.

    Хранить только одну сторону и делить значило бы вносить своё округление в
    число, полученное от источника.
    """
    repository = ExchangeRateRepository(session)
    await repository.upsert_many(
        [
            _rate(base=Currency.RSD, quote=Currency.EUR, rate="0.008532"),
            _rate(base=Currency.EUR, quote=Currency.RSD, rate="117.05"),
        ]
    )
    await session.commit()

    assert await repository.existing(
        {
            (Currency.RSD, Currency.EUR, _DAY),
            (Currency.EUR, Currency.RSD, _DAY),
        }
    ) == {
        (Currency.RSD, Currency.EUR, _DAY),
        (Currency.EUR, Currency.RSD, _DAY),
    }


async def test_rate_to_itself_is_rejected_by_the_schema(session: AsyncSession) -> None:
    """Курса валюты к себе самой не бывает: он всегда единица.

    Строки, единственная роль которых — когда-нибудь оказаться не единицей, в
    таблице не нужны, поэтому запрет стоит в схеме, а не в договорённости.
    """
    session.add(
        ExchangeRateORM(
            base_currency=Currency.EUR,
            quote_currency=Currency.EUR,
            rate_date=_DAY,
            rate=Decimal("1"),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_non_positive_rate_is_rejected_by_the_schema(session: AsyncSession) -> None:
    """Нулевой или отрицательный курс обнулил бы или перевернул все суммы."""
    session.add(
        ExchangeRateORM(
            base_currency=Currency.USD,
            quote_currency=Currency.EUR,
            rate_date=_DAY,
            rate=Decimal("0"),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_precision_survives_the_column(session: AsyncSession) -> None:
    """Двенадцать знаков после запятой доезжают целиком.

    Денежные два знака округлили бы курс RSD→EUR (0.0085…) в ноль и обнулили бы
    каждую динарную операцию.
    """
    repository = ExchangeRateRepository(session)
    await repository.upsert_many([_rate(rate="0.008532621500")])
    await session.commit()

    stored = await session.get(ExchangeRateORM, 1)
    assert stored is not None
    assert stored.rate == Decimal("0.008532621500")
