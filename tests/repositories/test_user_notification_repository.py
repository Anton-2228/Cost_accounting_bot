"""Тесты репозитория исходящих сообщений.

Основной предмет — выборка для фоновой рассылки: она обходит очередь по всем
документам сразу и обязана отдавать адрес получателя. Ошибка здесь означала бы,
что сообщение уходит не тому пользователю, а такое не поймает ни один тест
уровнем выше.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.user_message import UserMessage
from api.enums import Language, NotificationKind
from api.repositories.user_notification_repository import UserNotificationRepository
from tests.factories import create_spreadsheet, create_user


def _message(label: str) -> UserMessage:
    """Сообщение, отличимое от соседних по параметру."""
    return UserMessage(code="import_ok", params={"sheet": label})


async def test_pending_carries_the_recipient(session: AsyncSession) -> None:
    """Недоставленное приезжает вместе с telegram_id и языком владельца."""
    user = await create_user(
        session, telegram_id=555_001, language=Language.RU
    )
    spreadsheet = await create_spreadsheet(session, user=user, ready=True)
    assert spreadsheet.id is not None

    repository = UserNotificationRepository(session)
    await repository.notify(
        spreadsheet.id, NotificationKind.TABLE_READY, _message("Таблица готова")
    )

    pending = await repository.list_undelivered_all(limit=10)

    assert len(pending) == 1
    assert pending[0].telegram_id == 555_001
    assert pending[0].spreadsheet_id == spreadsheet.id
    assert pending[0].kind is NotificationKind.TABLE_READY
    assert pending[0].params == {"sheet": "Таблица готова"}
    assert pending[0].language is Language.RU


async def test_pending_covers_all_spreadsheets(session: AsyncSession) -> None:
    """Выборка идёт по всей очереди, а не по одному документу.

    Ровно это отличает её от `list_undelivered`: у рассылки нет документа, с
    которого начать, — она и существует, чтобы его не спрашивать.
    """
    first = await create_spreadsheet(session, user=await create_user(session, telegram_id=1))
    second = await create_spreadsheet(session, user=await create_user(session, telegram_id=2))
    assert first.id is not None
    assert second.id is not None

    repository = UserNotificationRepository(session)
    await repository.notify(first.id, NotificationKind.ROLLOVER, _message("первое"))
    await repository.notify(second.id, NotificationKind.SYNC_FAILED, _message("второе"))

    pending = await repository.list_undelivered_all(limit=10)

    assert [item.telegram_id for item in pending] == [1, 2]


async def test_delivered_are_not_returned(session: AsyncSession) -> None:
    """Подтверждённое сообщение из рассылки уходит и повторно не отправляется."""
    spreadsheet = await create_spreadsheet(session)
    assert spreadsheet.id is not None

    repository = UserNotificationRepository(session)
    notification = await repository.notify(
        spreadsheet.id, NotificationKind.IMPORT_ERROR, _message("ошибка разбора")
    )
    assert notification.id is not None

    await repository.mark_delivered(
        notification.id, spreadsheet.id, at=datetime.now(tz=UTC)
    )

    assert await repository.list_undelivered_all(limit=10) == []


async def test_pending_are_ordered_by_appearance(session: AsyncSession) -> None:
    """Порядок — порядок появления: «таблица готова» раньше «таблица обновилась»."""
    spreadsheet = await create_spreadsheet(session)
    assert spreadsheet.id is not None

    repository = UserNotificationRepository(session)
    await repository.notify(spreadsheet.id, NotificationKind.TABLE_READY, _message("первое"))
    await repository.notify(spreadsheet.id, NotificationKind.ROLLOVER, _message("второе"))
    await repository.notify(spreadsheet.id, NotificationKind.ROLLOVER, _message("третье"))

    pending = await repository.list_undelivered_all(limit=10)

    assert [item.params["sheet"] for item in pending] == ["первое", "второе", "третье"]


async def test_limit_leaves_the_tail_in_the_queue(session: AsyncSession) -> None:
    """Лимит режет хвост, а не теряет его: остаток уйдёт следующим проходом."""
    spreadsheet = await create_spreadsheet(session)
    assert spreadsheet.id is not None

    repository = UserNotificationRepository(session)
    for number in range(5):
        await repository.notify(spreadsheet.id, NotificationKind.ROLLOVER, _message(str(number)))

    assert len(await repository.list_undelivered_all(limit=2)) == 2
    assert len(await repository.list_undelivered_all(limit=10)) == 5
