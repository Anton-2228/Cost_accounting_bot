"""Тесты выдачи уведомлений боту."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import NotificationKind
from api.exceptions.base import NotFoundError
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.notification_service import NotificationService
from tests import factories


async def test_undelivered_notifications_are_listed_without_ready_table(
    session: AsyncSession,
    notification_service: NotificationService,
) -> None:
    """Готовность таблицы не требуется: первое же уведомление — «таблица готова».

    Требовать готовности, чтобы его прочитать, было бы замкнутым кругом.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    await UserNotificationRepository(session).notify(
        spreadsheet.id, NotificationKind.TABLE_READY, "Таблица готова"
    )
    await session.commit()

    notifications = await notification_service.list_undelivered(spreadsheet.id)
    assert [item.text for item in notifications] == ["Таблица готова"]


async def test_delivered_notification_disappears_from_the_queue(
    session: AsyncSession,
    notification_service: NotificationService,
) -> None:
    """Подтверждение убирает сообщение из выдачи, но не из истории.

    История полезна при разборе жалоб «мне ничего не пришло».
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    notifications = UserNotificationRepository(session)
    created = await notifications.notify(
        spreadsheet.id, NotificationKind.ROLLOVER, "Начался новый период"
    )
    await session.commit()
    assert created.id is not None

    await notification_service.mark_delivered(spreadsheet.id, created.id)
    assert await notification_service.list_undelivered(spreadsheet.id) == []

    stored = await notifications.get_by_id(created.id)
    assert stored is not None
    assert stored.delivered_at is not None


async def test_repeated_confirmation_is_not_an_error(
    session: AsyncSession,
    notification_service: NotificationService,
) -> None:
    """Повторное подтверждение — норма: бот мог перезапуститься после отправки."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    created = await UserNotificationRepository(session).notify(
        spreadsheet.id, NotificationKind.ROLLOVER, "Начался новый период"
    )
    await session.commit()
    assert created.id is not None

    await notification_service.mark_delivered(spreadsheet.id, created.id)
    await notification_service.mark_delivered(spreadsheet.id, created.id)


async def test_confirmation_of_alien_notification_is_not_found(
    session: AsyncSession,
    notification_service: NotificationService,
) -> None:
    """Сообщение чужого документа подтвердить нельзя."""
    spreadsheet = await factories.create_spreadsheet(session)
    stranger = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None and stranger.id is not None

    alien = await UserNotificationRepository(session).notify(
        stranger.id, NotificationKind.ROLLOVER, "Чужое"
    )
    await session.commit()
    assert alien.id is not None

    with pytest.raises(NotFoundError):
        await notification_service.mark_delivered(spreadsheet.id, alien.id)
