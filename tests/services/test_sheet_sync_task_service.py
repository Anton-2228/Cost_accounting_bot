"""Тесты выдачи задач очереди и отчётов о работе."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.enums import NotificationKind, SheetTarget
from api.exceptions.base import NotFoundError
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.sheet_sync_task_service import SheetSyncTaskService
from tests import factories


async def test_claim_returns_and_releases_the_lock(
    session: AsyncSession,
    sheet_sync_task_service: SheetSyncTaskService,
) -> None:
    """Забранная задача сразу фиксируется коммитом.

    `claim` держит строки под `FOR UPDATE`, а блокировки живут до конца
    транзакции: не закоммитить — значит запереть очередь на всё время
    перерисовки листов.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    tasks = SheetSyncTaskRepository(session)
    await tasks.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    claimed = await sheet_sync_task_service.claim()
    assert [task.target for task in claimed] == [SheetTarget.CATEGORIES]
    assert not session.in_transaction()

    # Повторный claim ничего не отдаёт: задача уже занята.
    assert await sheet_sync_task_service.claim() == []


async def test_complete_removes_task(
    session: AsyncSession,
    sheet_sync_task_service: SheetSyncTaskService,
) -> None:
    """Успешно перерисованный лист уходит из очереди."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    tasks = SheetSyncTaskRepository(session)
    await tasks.enqueue(spreadsheet.id, SheetTarget.BILLS)
    await session.commit()

    claimed = await sheet_sync_task_service.claim()
    task = claimed[0]
    assert task.id is not None and task.requested_at is not None

    assert await sheet_sync_task_service.complete(task.id, task.requested_at) is True
    assert await tasks.list_by_spreadsheet(spreadsheet.id) == []


async def test_complete_keeps_task_changed_during_work(
    session: AsyncSession,
    sheet_sync_task_service: SheetSyncTaskService,
) -> None:
    """Изменённый во время работы лист остаётся в очереди и освобождается.

    Пока воркер рисовал, пользователь мог сделать ещё одну операцию — она подняла
    бы `requested_at`. Безусловное удаление потеряло бы эту правку до следующей.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    tasks = SheetSyncTaskRepository(session)
    await tasks.enqueue(spreadsheet.id, SheetTarget.BILLS)
    await session.commit()

    claimed = await sheet_sync_task_service.claim()
    task = claimed[0]
    assert task.id is not None and task.requested_at is not None

    stale = task.requested_at - timedelta(seconds=1)
    assert await sheet_sync_task_service.complete(task.id, stale) is False

    remaining = await tasks.list_by_spreadsheet(spreadsheet.id)
    assert [item.id for item in remaining] == [task.id]
    # Захват снят: задачу должен получить следующий заход.
    assert remaining[0].claimed_at is None


async def test_fail_delays_retry_and_alerts_only_when_persistent(
    session: AsyncSession,
    sheet_sync_task_service: SheetSyncTaskService,
) -> None:
    """Первые неудачи молчат, а затянувшиеся — доходят до пользователя.

    Недоступность Google обычно проходит сама. Но если лист не удаётся обновить
    раз за разом, пользователь видит застывшую таблицу и не понимает почему.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    tasks = SheetSyncTaskRepository(session)
    await tasks.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    task = (await sheet_sync_task_service.claim())[0]
    assert task.id is not None

    notifications = UserNotificationRepository(session)
    for attempt in range(1, constants.SHEET_SYNC_ALERT_ATTEMPTS):
        await sheet_sync_task_service.fail(task.id, f"Google вернул 429 ({attempt})")
        assert await notifications.list_undelivered(spreadsheet.id) == []

    await sheet_sync_task_service.fail(task.id, "Google вернул 429")
    alerts = await notifications.list_undelivered(spreadsheet.id)
    assert [item.kind for item in alerts] == [NotificationKind.SYNC_FAILED]

    stored = (await tasks.list_by_spreadsheet(spreadsheet.id))[0]
    assert stored.attempts == constants.SHEET_SYNC_ALERT_ATTEMPTS
    assert stored.last_error == "Google вернул 429"
    assert stored.claimed_at is None
    assert stored.next_attempt_at is not None


async def test_fail_of_unknown_task(
    sheet_sync_task_service: SheetSyncTaskService,
) -> None:
    """Отчёт по несуществующей задаче — 404."""
    with pytest.raises(NotFoundError):
        await sheet_sync_task_service.fail(123456, "неважно")


async def test_terminal_failure_notifies_immediately(
    session: AsyncSession,
    sheet_sync_task_service: SheetSyncTaskService,
) -> None:
    """О терминальной ошибке пользователю говорят с первой же попытки.

    Ждать пятой значило бы молчать полчаса о том, что известно сразу: документ
    удалён или доступ отозван, и само это не пройдёт.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    tasks = SheetSyncTaskRepository(session)
    await tasks.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    task = (await sheet_sync_task_service.claim())[0]
    assert task.id is not None

    await sheet_sync_task_service.fail(task.id, "Google вернул 403", terminal=True)

    alerts = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in alerts] == [NotificationKind.SYNC_FAILED]
    assert "403" in alerts[0].text

    # Задача осталась в очереди: доступ могут вернуть, и лист догонит сам.
    stored = (await tasks.list_by_spreadsheet(spreadsheet.id))[0]
    assert stored.attempts == 1
    assert stored.claimed_at is None
