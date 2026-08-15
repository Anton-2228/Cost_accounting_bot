"""Эндпоинты исходящих сообщений пользователю."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.dependencies.services import get_notification_service
from api.responses.common.items_response import ItemsResponse
from api.responses.notifications.user_notification_response import UserNotificationResponse
from api.services.notification_service import NotificationService

router = APIRouter(prefix="/spreadsheets/{spreadsheet_id}/notifications", tags=["notifications"])


@router.get("", response_model=ItemsResponse[UserNotificationResponse])
async def list_notifications(
    spreadsheet_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> ItemsResponse[UserNotificationResponse]:
    """Сообщения, которые бот ещё не показал пользователю.

    Нужны потому, что у фоновой работы нет способа ответить пользователю
    синхронно: лист читает отдельный сервис по очереди, и ошибка разбора рождается
    тогда, когда HTTP-запроса пользователя уже нет.
    """
    notifications = await service.list_undelivered(spreadsheet_id)
    return ItemsResponse(
        items=[UserNotificationResponse.model_validate(item) for item in notifications]
    )


@router.post("/{notification_id}/delivered", status_code=status.HTTP_204_NO_CONTENT)
async def mark_delivered(
    spreadsheet_id: int,
    notification_id: int,
    service: NotificationService = Depends(get_notification_service),
) -> None:
    """Подтверждает, что сообщение показано.

    Подтверждение отдельно от чтения: упади бот между «прочитал» и «отправил»,
    сообщение должно остаться в очереди, а не исчезнуть. Повторное подтверждение
    — нормальный случай и ошибкой не считается.
    """
    await service.mark_delivered(spreadsheet_id, notification_id)
