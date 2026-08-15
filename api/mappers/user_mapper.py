"""Маппер пользователя."""

from __future__ import annotations

from api.domain.user import User
from api.mappers.base import BaseMapper
from api.orm.user import UserORM


class UserMapper(BaseMapper[UserORM, User]):
    """Пользователь Telegram."""

    def to_domain(self, orm: UserORM) -> User:
        """Преобразует ORM-объект в доменную модель."""
        return User(
            id=orm.id,
            telegram_id=orm.telegram_id,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: User) -> UserORM:
        """Создаёт ORM-объект из доменной модели."""
        return UserORM(telegram_id=domain.telegram_id)
