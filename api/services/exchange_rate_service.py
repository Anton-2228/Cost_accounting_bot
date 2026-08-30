"""Наполнение кэша курсов по требованию подсчёта."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.db.transaction import commit
from api.domain.exchange_rate import ExchangeRate, RateRequirement
from api.enums import Currency
from api.rates.base import RateProvider, RateUnavailableError
from api.repositories.exchange_rate_repository import ExchangeRateRepository

logger = get_logger(__name__)


class ExchangeRateService:
    """Гарантирует, что к моменту агрегации нужные курсы лежат в БД.

    Остаток счёта и лист статистики считаются агрегатами в SQL, а курс нужен на
    дату каждой отдельной операции. Тянуть курсы внутри запроса нельзя, поэтому
    подсчёт устроен в два шага: сначала запрос собирает множество троек
    «из валюты, в валюту, на день», затем :meth:`ensure` дозагружает
    недостающие, и только потом идёт агрегат.

    Оба запроса — «что нужно» и «чем считать» — ходят по одним и тем же
    таблицам с одними и теми же условиями. Это не совпадение, а требование:
    отсутствующий курс превращается в `NULL` внутри `SUM`, а `SUM` молча
    пропускает `NULL`, и остаток занизился бы, ничем себя не выдав.
    """

    def __init__(
        self,
        session: AsyncSession,
        rates: ExchangeRateRepository,
        provider: RateProvider,
    ) -> None:
        self._session = session
        self._rates = rates
        self._provider = provider

    async def ensure(self, requirements: Collection[RateRequirement]) -> None:
        """Догружает в кэш всё, чего в нём нет.

        Идемпотентен и дёшев на повторных вызовах: при полном кэше делает один
        запрос к БД и ни одного во внешний источник.

        Бросает :class:`~api.rates.base.RateUnavailableError`, если источник
        недоступен, — сознательно, чтобы подсчёт упал, а не показал число,
        собранное из части операций.
        """
        wanted = {item for item in requirements if item[0] != item[1]}
        if not wanted:
            return

        missing = wanted - await self._rates.existing(wanted)
        if not missing:
            return

        fetched = await self._fetch(missing)
        if not fetched:
            return

        inserted = await self._rates.upsert_many(fetched)
        await commit(self._session)
        logger.info(
            "курсы: запрошено %d, не хватало %d, записано %d",
            len(wanted),
            len(missing),
            inserted,
        )

    async def _fetch(self, missing: set[RateRequirement]) -> list[ExchangeRate]:
        """Забирает недостающее у источника, группируя запросы по (база, день).

        Один поход отдаёт котировки базовой валюты ко всем остальным, поэтому
        запросов ровно столько, сколько различных пар «база + день», а не
        сколько недостающих курсов.

        Записывается **всё**, что пришло в ответе, а не только запрошенные
        котировки: они уже получены и оплачены походом, а завтрашний подсчёт по
        другой паре тех же валют не пойдёт в сеть повторно.
        """
        by_source: dict[tuple[Currency, date], set[Currency]] = defaultdict(set)
        for base, quote, day in missing:
            by_source[(base, day)].add(quote)

        collected: list[ExchangeRate] = []
        for (base, day), quotes in sorted(
            by_source.items(),
            key=lambda item: (item[0][0].value, item[0][1]),
        ):
            rates = await self._provider.rates_on(base, day)
            self._require(base, day, quotes, rates)
            collected.extend(
                ExchangeRate(
                    base_currency=base,
                    quote_currency=quote,
                    rate_date=day,
                    rate=rate,
                )
                for quote, rate in rates.items()
            )
        return collected

    @staticmethod
    def _require(
        base: Currency,
        day: date,
        wanted: set[Currency],
        received: dict[Currency, Decimal],
    ) -> None:
        """Падает, если источник ответил, но нужной котировки в ответе нет.

        Пропустить такой пробел нельзя. Курс не попал бы в кэш, агрегат получил
        бы на его месте `NULL`, `SUM` молча выбросил бы слагаемое — и остаток
        счёта оказался бы занижен ровно на эту операцию, ничем себя не выдав.
        Из двух исходов — «ошибка» и «правдоподобное неверное число» — здесь
        выбран первый: задача перерисовки повторится, а в таблице до тех пор
        останутся прежние верные значения.
        """
        absent = wanted - received.keys()
        if not absent:
            return
        codes = sorted(currency.value for currency in absent)
        raise RateUnavailableError(
            "Источник курсов не вернул часть запрошенных котировок",
            details={"base": base.value, "quotes": codes, "day": day.isoformat()},
        )
