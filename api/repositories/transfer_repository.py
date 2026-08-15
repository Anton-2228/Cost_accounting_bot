"""Репозиторий переводов между счетами."""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.transfer import Transfer
from api.mappers.transfer_mapper import TransferMapper
from api.orm.transfer import TransferORM
from api.repositories.base import BaseRepository


class TransferRepository(BaseRepository[TransferORM, Transfer]):
    """Доступ к переводам."""

    orm_type = TransferORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TransferMapper())

    async def list_by_period(
        self,
        period_id: int,
        *,
        include_deleted: bool = False,
    ) -> list[Transfer]:
        """Возвращает переводы периода по возрастанию id."""
        stmt = select(TransferORM).where(TransferORM.period_id == period_id)
        if not include_deleted:
            stmt = stmt.where(TransferORM.deleted_at.is_(None))
        rows = (await self._session.scalars(stmt.order_by(TransferORM.id))).all()
        return self._mapper.to_domain_list(rows)

    async def get_for_spreadsheet(
        self,
        transfer_id: int,
        spreadsheet_id: int,
        *,
        include_deleted: bool = False,
    ) -> Transfer | None:
        """Возвращает перевод, только если он принадлежит указанному документу."""
        stmt = select(TransferORM).where(
            TransferORM.id == transfer_id,
            TransferORM.spreadsheet_id == spreadsheet_id,
        )
        if not include_deleted:
            stmt = stmt.where(TransferORM.deleted_at.is_(None))
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def get_last_in_period(self, period_id: int) -> Transfer | None:
        """Возвращает последний добавленный живой перевод периода."""
        orm = (
            await self._session.scalars(
                select(TransferORM)
                .where(TransferORM.period_id == period_id, TransferORM.deleted_at.is_(None))
                .order_by(TransferORM.id.desc())
                .limit(1)
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def exists_by_source(self, source_id: int) -> bool:
        """Участвует ли счёт хотя бы в одном живом переводе (любой стороной)."""
        found = await self._session.scalar(
            select(TransferORM.id)
            .where(
                or_(
                    TransferORM.from_source_id == source_id,
                    TransferORM.to_source_id == source_id,
                ),
                TransferORM.deleted_at.is_(None),
            )
            .limit(1)
        )
        return found is not None
