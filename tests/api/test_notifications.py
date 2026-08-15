"""Тесты эндпоинтов уведомлений."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import NotificationKind
from api.repositories.user_notification_repository import UserNotificationRepository
from tests import factories


async def test_notifications_are_listed_and_confirmed(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Бот читает сообщения и подтверждает их отдельным запросом.

    Подтверждение отдельно от чтения: упади бот между «прочитал» и «отправил»,
    сообщение должно остаться в очереди.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    created = await UserNotificationRepository(session).notify(
        spreadsheet.id, NotificationKind.ROLLOVER, "Начался новый расчётный период"
    )
    await session.commit()

    base = f"/api/v1/spreadsheets/{spreadsheet.id}/notifications"
    listed = await client.get(base)
    assert listed.status_code == 200
    assert [item["text"] for item in listed.json()["items"]] == [
        "Начался новый расчётный период"
    ]

    confirmed = await client.post(f"{base}/{created.id}/delivered")
    assert confirmed.status_code == 204
    assert (await client.get(base)).json()["items"] == []

    # Повтор — не ошибка: бот мог перезапуститься уже после отправки.
    assert (await client.post(f"{base}/{created.id}/delivered")).status_code == 204


async def test_unknown_notification_is_404(client: AsyncClient, session: AsyncSession) -> None:
    """Подтверждение несуществующего сообщения — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/notifications/98765/delivered"
    )
    assert response.status_code == 404
