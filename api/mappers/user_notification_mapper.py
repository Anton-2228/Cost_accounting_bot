"""Маппер сообщения пользователю."""

from __future__ import annotations

from api.domain.user_notification import UserNotification
from api.mappers.base import BaseMapper
from api.orm.user_notification import UserNotificationORM


class UserNotificationMapper(BaseMapper[UserNotificationORM, UserNotification]):
    """Уведомление о результате фоновой работы."""

    def to_domain(self, orm: UserNotificationORM) -> UserNotification:
        """Преобразует ORM-объект в доменную модель."""
        return UserNotification(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            kind=orm.kind,
            text=orm.text,
            delivered_at=orm.delivered_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: UserNotification) -> UserNotificationORM:
        """Создаёт ORM-объект из доменной модели."""
        return UserNotificationORM(
            spreadsheet_id=domain.spreadsheet_id,
            kind=domain.kind,
            text=domain.text,
            delivered_at=domain.delivered_at,
        )
