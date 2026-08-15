"""Репозиторий доступов к Google-документу."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.spreadsheet_access import SpreadsheetAccess
from api.mappers.spreadsheet_access_mapper import SpreadsheetAccessMapper
from api.orm.spreadsheet_access import SpreadsheetAccessORM
from api.repositories.base import BaseRepository, affected_rows


class SpreadsheetAccessRepository(BaseRepository[SpreadsheetAccessORM, SpreadsheetAccess]):
    """Доступ к списку почт, которым открыт документ."""

    orm_type = SpreadsheetAccessORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SpreadsheetAccessMapper())

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[SpreadsheetAccess]:
        """Возвращает все доступы документа."""
        rows = (
            await self._session.scalars(
                select(SpreadsheetAccessORM)
                .where(SpreadsheetAccessORM.spreadsheet_id == spreadsheet_id)
                .order_by(SpreadsheetAccessORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def list_pending(self, spreadsheet_id: int) -> list[SpreadsheetAccess]:
        """Возвращает доступы, которые ещё не выданы в Google."""
        rows = (
            await self._session.scalars(
                select(SpreadsheetAccessORM)
                .where(
                    SpreadsheetAccessORM.spreadsheet_id == spreadsheet_id,
                    SpreadsheetAccessORM.granted_at.is_(None),
                )
                .order_by(SpreadsheetAccessORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def get_by_email(self, spreadsheet_id: int, email: str) -> SpreadsheetAccess | None:
        """Находит доступ по почте."""
        orm = (
            await self._session.scalars(
                select(SpreadsheetAccessORM).where(
                    SpreadsheetAccessORM.spreadsheet_id == spreadsheet_id,
                    SpreadsheetAccessORM.email == email,
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def mark_granted(self, access_id: int, *, at: datetime) -> bool:
        """Отмечает доступ фактически выданным.

        Условие `granted_at IS NULL` не даёт повторной выдаче переписать момент
        первой.
        """
        result = await self._session.execute(
            update(SpreadsheetAccessORM)
            .where(
                SpreadsheetAccessORM.id == access_id,
                SpreadsheetAccessORM.granted_at.is_(None),
            )
            .values(granted_at=at)
        )
        await self._session.flush()
        return bool(affected_rows(result))
