"""Репозиторий учётных таблиц."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.spreadsheet import Spreadsheet
from api.mappers.spreadsheet_mapper import SpreadsheetMapper
from api.orm.spreadsheet import SpreadsheetORM
from api.orm.user import UserORM
from api.repositories.base import BaseRepository


class SpreadsheetRepository(BaseRepository[SpreadsheetORM, Spreadsheet]):
    """Доступ к учётным таблицам."""

    orm_type = SpreadsheetORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SpreadsheetMapper())

    async def get_by_user_id(self, user_id: int) -> Spreadsheet | None:
        """Находит таблицу пользователя. Она ровно одна: `user_id` уникален."""
        orm = (
            await self._session.scalars(
                select(SpreadsheetORM).where(SpreadsheetORM.user_id == user_id)
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def get_by_telegram_id(self, telegram_id: int) -> Spreadsheet | None:
        """Находит таблицу по telegram_id владельца."""
        orm = (
            await self._session.scalars(
                select(SpreadsheetORM)
                .join(UserORM, UserORM.id == SpreadsheetORM.user_id)
                .where(UserORM.telegram_id == telegram_id)
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def get_by_google_id(self, google_spreadsheet_id: str) -> Spreadsheet | None:
        """Находит таблицу по идентификатору Google-документа."""
        orm = (
            await self._session.scalars(
                select(SpreadsheetORM).where(
                    SpreadsheetORM.google_spreadsheet_id == google_spreadsheet_id
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def list_all(self) -> list[Spreadsheet]:
        """Возвращает все таблицы. Нужен ролловеру для обхода документов."""
        rows = (
            await self._session.scalars(select(SpreadsheetORM).order_by(SpreadsheetORM.id))
        ).all()
        return self._mapper.to_domain_list(rows)

    async def set_google_spreadsheet_id(
        self,
        spreadsheet_id: int,
        google_spreadsheet_id: str,
    ) -> Spreadsheet | None:
        """Записывает идентификатор созданного документа и возвращает его целиком.

        Вызывается после подтверждения от Google: до этого момента поле пусто,
        и по нему видно, что документ ещё предстоит создать.

        Обновлённая модель приходит через `RETURNING`, а не читается следом:
        `expire_on_commit=False` оставляет в сессии прежний объект, и повторный
        `get_by_id` мог бы отдать документ с пустым `google_spreadsheet_id` —
        то есть «ещё не готов» сразу после того, как он стал готов.
        """
        orm = (
            await self._session.scalars(
                update(SpreadsheetORM)
                .where(SpreadsheetORM.id == spreadsheet_id)
                .values(google_spreadsheet_id=google_spreadsheet_id)
                .returning(SpreadsheetORM)
            )
        ).one_or_none()
        await self._session.flush()
        return None if orm is None else self._mapper.to_domain(orm)
