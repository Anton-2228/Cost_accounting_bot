"""Репозиторий исходящих сообщений пользователю."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.pending_notification import PendingNotification
from api.domain.user_notification import UserNotification
from api.enums import NotificationKind
from api.mappers.user_notification_mapper import UserNotificationMapper
from api.orm.spreadsheet import SpreadsheetORM
from api.orm.user import UserORM
from api.orm.user_notification import UserNotificationORM
from api.repositories.base import BaseRepository, affected_rows


class UserNotificationRepository(BaseRepository[UserNotificationORM, UserNotification]):
    """Доступ к очереди сообщений, которые бот должен показать пользователю."""

    orm_type = UserNotificationORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, UserNotificationMapper())

    async def notify(
        self,
        spreadsheet_id: int,
        kind: NotificationKind,
        text: str,
    ) -> UserNotification:
        """Кладёт сообщение в очередь на отправку.

        Вызывается в той же транзакции, что и событие, о котором сообщает: если
        импорт откатился, уведомление о его провале не должно остаться висеть.
        """
        return await self.add(
            UserNotification(spreadsheet_id=spreadsheet_id, kind=kind, text=text)
        )

    async def list_undelivered(self, spreadsheet_id: int) -> list[UserNotification]:
        """Возвращает неотправленные сообщения документа в порядке появления."""
        rows = (
            await self._session.scalars(
                select(UserNotificationORM)
                .where(
                    UserNotificationORM.spreadsheet_id == spreadsheet_id,
                    UserNotificationORM.delivered_at.is_(None),
                )
                .order_by(UserNotificationORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def list_undelivered_all(self, limit: int) -> list[PendingNotification]:
        """Недоставленные сообщения всех документов вместе с адресом получателя.

        Нужен фоновой рассылке: она обходит очередь целиком, а не документ за
        документом, и обязана знать, в какой чат отправлять. `telegram_id` лежит
        через две таблицы, поэтому здесь join, а не отдельный запрос на каждое
        сообщение.

        Порядок по `id` — порядок появления: пользователь должен увидеть «таблица
        готова» раньше, чем «таблица обновилась».
        """
        rows = (
            await self._session.execute(
                select(
                    UserNotificationORM.id,
                    UserNotificationORM.spreadsheet_id,
                    UserORM.telegram_id,
                    UserNotificationORM.kind,
                    UserNotificationORM.text,
                )
                .join(SpreadsheetORM, SpreadsheetORM.id == UserNotificationORM.spreadsheet_id)
                .join(UserORM, UserORM.id == SpreadsheetORM.user_id)
                .where(UserNotificationORM.delivered_at.is_(None))
                .order_by(UserNotificationORM.id)
                .limit(limit)
            )
        ).all()
        return [
            PendingNotification(
                id=row.id,
                spreadsheet_id=row.spreadsheet_id,
                telegram_id=row.telegram_id,
                kind=row.kind,
                text=row.text,
            )
            for row in rows
        ]

    async def mark_delivered(
        self,
        notification_id: int,
        spreadsheet_id: int,
        *,
        at: datetime,
    ) -> bool:
        """Отмечает сообщение отправленным. Идемпотентно.

        Условие `delivered_at IS NULL` делает повторное подтверждение
        безобидным: бот может прислать его дважды после своего перезапуска, и
        время первой отправки при этом не сдвинется.
        """
        result = await self._session.execute(
            update(UserNotificationORM)
            .where(
                UserNotificationORM.id == notification_id,
                UserNotificationORM.spreadsheet_id == spreadsheet_id,
                UserNotificationORM.delivered_at.is_(None),
            )
            .values(delivered_at=at)
        )
        await self._session.flush()
        return bool(affected_rows(result))
