"""Репозиторий кэша курсов валют."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.exchange_rate import ExchangeRate, RateRequirement
from api.mappers.exchange_rate_mapper import ExchangeRateMapper
from api.orm.exchange_rate import ExchangeRateORM
from api.repositories.base import BaseRepository


class ExchangeRateRepository(BaseRepository[ExchangeRateORM, ExchangeRate]):
    """Курсы валют по дням.

    Кэш общий для всех документов, поэтому фильтра по `spreadsheet_id` здесь нет
    ни в одном методе — см. :class:`api.orm.exchange_rate.ExchangeRateORM`.
    """

    orm_type = ExchangeRateORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ExchangeRateMapper())

    async def existing(
        self,
        requirements: Collection[RateRequirement],
    ) -> set[RateRequirement]:
        """Какие из запрошенных троек уже лежат в кэше.

        Спрашивается ровно тем же ключом, каким потом читает агрегат, поэтому
        «есть в кэше» и «найдётся при подсчёте» — одно и то же утверждение.
        Разойдись эти два условия, недостающий курс дал бы `NULL` внутри `SUM`,
        а `SUM` молча пропускает `NULL`: остаток занизился бы без единого
        признака ошибки.
        """
        if not requirements:
            return set()

        key = tuple_(
            ExchangeRateORM.base_currency,
            ExchangeRateORM.quote_currency,
            ExchangeRateORM.rate_date,
        )
        rows = (
            await self._session.execute(
                select(
                    ExchangeRateORM.base_currency,
                    ExchangeRateORM.quote_currency,
                    ExchangeRateORM.rate_date,
                ).where(key.in_(list(requirements)))
            )
        ).all()
        return {(row[0], row[1], row[2]) for row in rows}

    async def upsert_many(self, rates: Sequence[ExchangeRate]) -> int:
        """Добавляет курсы, не трогая уже записанные. Возвращает число вставленных.

        `DO NOTHING`, а не `DO UPDATE`: курс за прошедший день — факт, и
        перезапись означала бы, что вчерашний остаток счёта сегодня стал другим.
        Конфликт здесь нормален и ожидаем: два подсчёта могут одновременно
        обнаружить нехватку одного и того же дня.
        """
        if not rates:
            return 0

        stmt = (
            pg_insert(ExchangeRateORM)
            .values(
                [
                    {
                        "base_currency": rate.base_currency,
                        "quote_currency": rate.quote_currency,
                        "rate_date": rate.rate_date,
                        "rate": rate.rate,
                    }
                    for rate in rates
                ]
            )
            .on_conflict_do_nothing(constraint="uq_exchange_rates_pair_date")
            .returning(ExchangeRateORM.id)
        )
        inserted = (await self._session.scalars(stmt)).all()
        await self._session.flush()
        return len(inserted)
