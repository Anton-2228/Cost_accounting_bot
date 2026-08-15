"""Репозиторий учётных периодов."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.period import Period
from api.enums import PeriodStatus
from api.mappers.period_mapper import PeriodMapper
from api.orm.period import PeriodORM
from api.repositories.base import BaseRepository, affected_rows


class PeriodRepository(BaseRepository[PeriodORM, Period]):
    """Доступ к учётным периодам."""

    orm_type = PeriodORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PeriodMapper())

    async def ensure(self, spreadsheet_id: int, start_date: date, end_date: date) -> Period:
        """Возвращает период с указанным началом, создавая его при необходимости.

        Идемпотентность — то, ради чего периоды вынесены в таблицу. Ролловер
        может выполняться сколько угодно раз подряд и с любым отставанием:
        уникальный ключ `(spreadsheet_id, start_date)` не даст создать дубль, а
        `DO NOTHING` превращает повторный вызов в чтение.

        Прежний ролловер сдвигал указатель `start_date` в документе и срабатывал
        только при точном равенстве `today == end_date`. Простой сервиса в день
        сброса означал безвозвратно пропущенный месяц, а сбой на создании листа
        оставлял документ сломанным навсегда: указатель уже уехал, а листа нет.
        """
        stmt = (
            pg_insert(PeriodORM)
            .values(spreadsheet_id=spreadsheet_id, start_date=start_date, end_date=end_date)
            .on_conflict_do_nothing(constraint="uq_periods_spreadsheet_id_start_date")
            .returning(PeriodORM)
        )
        orm = (await self._session.scalars(stmt)).one_or_none()
        await self._session.flush()

        if orm is None:
            # Строка уже была: DO NOTHING ничего не вернул, читаем существующую.
            orm = (
                await self._session.scalars(
                    select(PeriodORM).where(
                        PeriodORM.spreadsheet_id == spreadsheet_id,
                        PeriodORM.start_date == start_date,
                    )
                )
            ).one()
        return self._mapper.to_domain(orm)

    async def get_for_spreadsheet(self, period_id: int, spreadsheet_id: int) -> Period | None:
        """Возвращает период, только если он принадлежит указанному документу."""
        orm = (
            await self._session.scalars(
                select(PeriodORM).where(
                    PeriodORM.id == period_id,
                    PeriodORM.spreadsheet_id == spreadsheet_id,
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def get_containing(self, spreadsheet_id: int, day: date) -> Period | None:
        """Находит период, которому принадлежит дата.

        Границы полуинтервальные: `start_date <= day < end_date`. Прежний код
        отбирал записи включительным `BETWEEN`, из-за чего операция в день
        `end_date` попадала сразу в два периода.
        """
        orm = (
            await self._session.scalars(
                select(PeriodORM).where(
                    PeriodORM.spreadsheet_id == spreadsheet_id,
                    PeriodORM.start_date <= day,
                    PeriodORM.end_date > day,
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def get_latest(self, spreadsheet_id: int) -> Period | None:
        """Возвращает самый поздний период документа."""
        orm = (
            await self._session.scalars(
                select(PeriodORM)
                .where(PeriodORM.spreadsheet_id == spreadsheet_id)
                .order_by(PeriodORM.start_date.desc())
                .limit(1)
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[Period]:
        """Возвращает все периоды документа по возрастанию даты начала."""
        rows = (
            await self._session.scalars(
                select(PeriodORM)
                .where(PeriodORM.spreadsheet_id == spreadsheet_id)
                .order_by(PeriodORM.start_date)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def list_open(self, spreadsheet_id: int) -> list[Period]:
        """Возвращает незакрытые периоды документа."""
        rows = (
            await self._session.scalars(
                select(PeriodORM)
                .where(
                    PeriodORM.spreadsheet_id == spreadsheet_id,
                    PeriodORM.status == PeriodStatus.OPEN,
                )
                .order_by(PeriodORM.start_date)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def close(self, period_id: int, *, at: datetime) -> bool:
        """Закрывает период; False, если он уже был закрыт.

        Условие по статусу делает закрытие идемпотентным: повтор не переписывает
        момент первого закрытия.
        """
        result = await self._session.execute(
            update(PeriodORM)
            .where(PeriodORM.id == period_id, PeriodORM.status == PeriodStatus.OPEN)
            .values(status=PeriodStatus.CLOSED, closed_at=at)
        )
        await self._session.flush()
        return bool(affected_rows(result))
