"""Репозиторий операций."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.category_daily_total import CategoryDailyTotal
from api.domain.record import Record
from api.mappers.record_mapper import RecordMapper
from api.orm.record import RecordORM
from api.repositories.base import BaseRepository


class RecordRepository(BaseRepository[RecordORM, Record]):
    """Доступ к операциям реестра."""

    orm_type = RecordORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RecordMapper())

    async def list_by_period(
        self,
        period_id: int,
        *,
        include_deleted: bool = False,
    ) -> list[Record]:
        """Возвращает операции периода по возрастанию id.

        Отбор идёт по `period_id`, а не по диапазону дат: принадлежность
        операции месяцу — внешний ключ, поэтому граничная дата не может попасть
        сразу в два периода, как это было при включительном `BETWEEN`.
        """
        stmt = select(RecordORM).where(RecordORM.period_id == period_id)
        if not include_deleted:
            stmt = stmt.where(RecordORM.deleted_at.is_(None))
        rows = (await self._session.scalars(stmt.order_by(RecordORM.id))).all()
        return self._mapper.to_domain_list(rows)

    async def count_by_period(self, period_id: int) -> int:
        """Считает живые операции периода."""
        total = await self._session.scalar(
            select(func.count())
            .select_from(RecordORM)
            .where(RecordORM.period_id == period_id, RecordORM.deleted_at.is_(None))
        )
        return int(total or 0)

    async def get_last_in_period(self, period_id: int) -> Record | None:
        """Возвращает последнюю добавленную живую операцию периода."""
        orm = (
            await self._session.scalars(
                select(RecordORM)
                .where(RecordORM.period_id == period_id, RecordORM.deleted_at.is_(None))
                .order_by(RecordORM.id.desc())
                .limit(1)
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def get_for_spreadsheet(
        self,
        record_id: int,
        spreadsheet_id: int,
        *,
        include_deleted: bool = False,
    ) -> Record | None:
        """Возвращает операцию, только если она принадлежит указанному документу."""
        stmt = select(RecordORM).where(
            RecordORM.id == record_id,
            RecordORM.spreadsheet_id == spreadsheet_id,
        )
        if not include_deleted:
            stmt = stmt.where(RecordORM.deleted_at.is_(None))
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def daily_totals_by_category(self, period_id: int) -> list[CategoryDailyTotal]:
        """Считает дневные итоги по категориям за период одним запросом.

        Основа листа статистики. Суммы приходят в `Decimal` без округления:
        прежний код сворачивал их через `int()`, из-за чего терялись копейки, а
        расходы — они отрицательны — систематически занижались, ведь
        `int(-1234.56)` даёт `-1234`.
        """
        stmt = (
            select(
                RecordORM.category_id,
                RecordORM.added_at,
                func.sum(RecordORM.amount).label("total"),
            )
            .where(RecordORM.period_id == period_id, RecordORM.deleted_at.is_(None))
            .group_by(RecordORM.category_id, RecordORM.added_at)
            .order_by(RecordORM.category_id, RecordORM.added_at)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            CategoryDailyTotal(category_id=row.category_id, day=row.added_at, total=row.total)
            for row in rows
        ]

    async def exists_by_category(self, category_id: int) -> bool:
        """Есть ли живые операции у категории."""
        found = await self._session.scalar(
            select(RecordORM.id)
            .where(RecordORM.category_id == category_id, RecordORM.deleted_at.is_(None))
            .limit(1)
        )
        return found is not None

    async def exists_by_source(self, source_id: int) -> bool:
        """Есть ли живые операции у счёта."""
        found = await self._session.scalar(
            select(RecordORM.id)
            .where(RecordORM.source_id == source_id, RecordORM.deleted_at.is_(None))
            .limit(1)
        )
        return found is not None
