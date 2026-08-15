"""Выдача ботом накопленных сообщений пользователю."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.core.period import now_in_timezone
from api.domain.pending_notification import PendingNotification
from api.domain.user_notification import UserNotification
from api.exceptions.base import NotFoundError
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.base import BaseSpreadsheetService


class NotificationService(BaseSpreadsheetService):
    """Исходящие сообщения о фоновой работе.

    Готовность документа не проверяется намеренно: первое же уведомление —
    «таблица готова», и требовать готовности, чтобы его прочитать, было бы
    замкнутым кругом.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        notifications: UserNotificationRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._notifications = notifications

    async def list_undelivered(self, spreadsheet_id: int) -> list[UserNotification]:
        """Сообщения, которые бот ещё не показал пользователю."""
        await self._get(spreadsheet_id)
        return await self._notifications.list_undelivered(spreadsheet_id)

    async def list_pending(
        self,
        *,
        limit: int = constants.NOTIFICATION_PUSH_LIMIT,
    ) -> list[PendingNotification]:
        """Недоставленные сообщения всех документов — для фоновой рассылки.

        Документ здесь не проверяется: обход идёт по очереди, а не по запросу
        пользователя, и проверять нечего — сообщение существует, значит и
        документ существует (внешний ключ с каскадом).
        """
        return await self._notifications.list_undelivered_all(limit)

    async def mark_delivered(self, spreadsheet_id: int, notification_id: int) -> None:
        """Подтверждает отправку сообщения.

        Подтверждение отдельно от чтения: упади бот между «прочитал» и
        «отправил», сообщение должно остаться в очереди, а не исчезнуть.
        """
        spreadsheet = await self._get(spreadsheet_id)
        delivered = await self._notifications.mark_delivered(
            notification_id,
            spreadsheet_id,
            at=now_in_timezone(spreadsheet.timezone),
        )
        if not delivered:
            # Ничего не изменилось: либо сообщения нет, либо его уже
            # подтвердили. Повтор — нормальный случай (бот мог перезапуститься
            # после отправки), ошибкой считается только отсутствие.
            existing = await self._notifications.get_by_id(notification_id)
            if existing is None or existing.spreadsheet_id != spreadsheet_id:
                raise NotFoundError("notification")
        await self._commit()
