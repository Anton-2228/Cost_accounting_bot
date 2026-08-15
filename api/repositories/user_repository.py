"""Репозиторий пользователей."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.user import User
from api.mappers.user_mapper import UserMapper
from api.orm.user import UserORM
from api.repositories.base import BaseRepository


class UserRepository(BaseRepository[UserORM, User]):
    """Доступ к пользователям Telegram."""

    orm_type = UserORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserMapper())

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Находит пользователя по telegram_id.

        Результат однозначен: `telegram_id` уникален. В старой схеме уникальности
        не было, и запрос без `ORDER BY` возвращал произвольную из нескольких
        строк — какую именно, определял порядок строк в куче Postgres.
        """
        orm = (
            await self._session.scalars(select(UserORM).where(UserORM.telegram_id == telegram_id))
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def exists_by_telegram_id(self, telegram_id: int) -> bool:
        """Проверяет наличие пользователя без загрузки строки."""
        found = await self._session.scalar(
            select(UserORM.id).where(UserORM.telegram_id == telegram_id).limit(1)
        )
        return found is not None
