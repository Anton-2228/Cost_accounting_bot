"""Тесты очереди перерисовки листов.

Три свойства, ради которых очередь вообще существует: схлопывание потока правок
в одну задачу, безопасный захват несколькими воркерами и невозможность потерять
изменение, пришедшее во время обработки.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import constants
from api.enums import SheetTarget, SyncTaskKind
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_repeated_enqueue_collapses_into_one_task(session: AsyncSession) -> None:
    """Десять правок подряд оставляют одну задачу.

    Это и есть выигрыш очереди: лист перерисовывается один раз вместо десяти.
    Прежняя версия ходила в Google на каждую операцию отдельно.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    assert spreadsheet.id is not None

    repository = SheetSyncTaskRepository(session)
    for _ in range(10):
        await repository.enqueue(spreadsheet.id, SheetTarget.OPERATIONS, period.id)
    await session.commit()

    tasks = await repository.list_by_spreadsheet(spreadsheet.id)
    assert len(tasks) == 1
    assert tasks[0].target == SheetTarget.OPERATIONS


async def test_enqueue_moves_requested_at_forward(session: AsyncSession) -> None:
    """Повторный запрос двигает метку версии вперёд, а не создаёт вторую строку."""
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()
    first = (await repository.list_by_spreadsheet(spreadsheet.id))[0]

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()
    second = (await repository.list_by_spreadsheet(spreadsheet.id))[0]

    assert second.id == first.id
    assert first.requested_at is not None
    assert second.requested_at is not None
    assert second.requested_at > first.requested_at


async def test_targets_without_period_also_collapse(session: AsyncSession) -> None:
    """Схлопывание работает и для листов без периода.

    У `CATEGORIES`, `BILLS` и `STRUCTURE` период пуст. По умолчанию PostgreSQL
    считает NULL-ы различными, и без `NULLS NOT DISTINCT` уникальный ключ не
    сработал бы — задачи копились бы без предела.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    for _ in range(5):
        await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    assert len(await repository.list_by_spreadsheet(spreadsheet.id)) == 1


async def test_different_targets_do_not_collapse(session: AsyncSession) -> None:
    """Разные листы — разные задачи."""
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await repository.enqueue(spreadsheet.id, SheetTarget.BILLS)
    await repository.enqueue(spreadsheet.id, SheetTarget.OPERATIONS, period.id)
    await session.commit()

    tasks = await repository.list_by_spreadsheet(spreadsheet.id)
    assert {task.target for task in tasks} == {
        SheetTarget.CATEGORIES,
        SheetTarget.BILLS,
        SheetTarget.OPERATIONS,
    }


async def test_enqueue_many_tolerates_duplicate_keys(session: AsyncSession) -> None:
    """Одинаковые ключи в одном вызове не роняют оператор.

    PostgreSQL падает с «ON CONFLICT DO UPDATE command cannot affect row a
    second time», если один INSERT содержит два одинаковых ключа, поэтому
    репозиторий дедуплицирует их заранее.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue_many(
        [
            (spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.CATEGORIES, None),
            (spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.CATEGORIES, None),
            (spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None),
        ]
    )
    await session.commit()

    assert len(await repository.list_by_spreadsheet(spreadsheet.id)) == 2


async def test_claim_marks_task_and_hides_it_from_second_claim(session: AsyncSession) -> None:
    """Забранная задача не выдаётся повторно."""
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    claimed = await repository.claim()
    await session.commit()
    assert len(claimed) == 1

    assert await repository.claim() == []


async def test_two_workers_never_get_the_same_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """`SKIP LOCKED` разводит воркеров по разным задачам.

    Первый воркер держит блокировку в незавершённой транзакции; второй не ждёт
    его, а забирает другую задачу.
    """
    async with session_factory() as setup:
        spreadsheet = await factories.create_spreadsheet(setup)
        assert spreadsheet.id is not None
        repository = SheetSyncTaskRepository(setup)
        await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
        await repository.enqueue(spreadsheet.id, SheetTarget.BILLS)
        await setup.commit()
        spreadsheet_id = spreadsheet.id

    async with session_factory() as first, session_factory() as second:
        first_batch = await SheetSyncTaskRepository(first).claim(limit=1)
        second_batch = await SheetSyncTaskRepository(second).claim(limit=1)

        assert len(first_batch) == 1
        assert len(second_batch) == 1
        assert first_batch[0].id != second_batch[0].id

        await first.commit()
        await second.commit()

    async with session_factory() as check:
        remaining = await SheetSyncTaskRepository(check).list_by_spreadsheet(spreadsheet_id)
        assert all(task.claimed_at is not None for task in remaining)


async def test_complete_removes_task_when_nothing_changed(session: AsyncSession) -> None:
    """Задача, никем не тронутая за время работы, удаляется."""
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    task = (await repository.claim())[0]
    await session.commit()

    assert task.id is not None
    assert task.requested_at is not None
    assert await repository.complete(task.id, task.requested_at) is True
    await session.commit()

    assert await repository.list_by_spreadsheet(spreadsheet.id) == []


async def test_change_during_processing_is_not_lost(session: AsyncSession) -> None:
    """Правка, пришедшая во время перерисовки, не теряется.

    Сценарий: воркер забрал задачу и начал перерисовывать лист, пользователь в
    этот момент добавил операцию. Безусловное удаление задачи по завершении
    похоронило бы это изменение до следующей правки. Условие по `requested_at`
    не даёт удалить строку, и лист перерисовывается ещё раз.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    task = (await repository.claim())[0]
    await session.commit()
    assert task.id is not None
    assert task.requested_at is not None

    # Пользователь меняет данные, пока воркер работает.
    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    assert await repository.complete(task.id, task.requested_at) is False
    await repository.release(task.id)
    await session.commit()

    tasks = await repository.list_by_spreadsheet(spreadsheet.id)
    assert len(tasks) == 1
    assert tasks[0].claimed_at is None

    # Задача снова доступна для выборки.
    assert len(await repository.claim()) == 1


async def test_failure_increments_attempts_and_delays_retry(session: AsyncSession) -> None:
    """После ошибки задача возвращается в очередь с паузой и записанной причиной."""
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    task = (await repository.claim())[0]
    await session.commit()
    assert task.id is not None

    await repository.fail(task.id, "Google вернул 429")
    await session.commit()

    stored = (await repository.list_by_spreadsheet(spreadsheet.id))[0]
    assert stored.attempts == 1
    assert stored.claimed_at is None
    assert stored.last_error == "Google вернул 429"
    # Пауза ещё не истекла, поэтому задача не выбирается.
    assert await repository.claim() == []


async def test_new_change_cancels_backoff(session: AsyncSession) -> None:
    """Новая правка отменяет паузу: пользователь ждёт свежий лист, а не backoff.

    `LEAST(next_attempt_at, now())` ссылается на колонку таблицы. Если бы там
    стоял `excluded.next_attempt_at`, в нём лежал бы серверный `now()`
    вставляемой строки, `LEAST` выродился бы, и задача выбиралась бы немедленно
    всегда — backoff перестал бы работать вовсе.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()
    task = (await repository.claim())[0]
    await session.commit()
    assert task.id is not None

    await repository.fail(task.id, "временная ошибка")
    await session.commit()
    assert await repository.claim() == []

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    assert len(await repository.claim()) == 1


async def test_expired_lease_returns_task_to_the_queue(session: AsyncSession) -> None:
    """Задача, забранная умершим воркером, возвращается в очередь сама.

    Захват снимают `complete`, `release` и `fail`, но воркер может не дожить ни
    до одного из них: между `claim` и отчётом его способны убить рестарт, OOM
    или потеря сети. Без срока аренды такая задача осталась бы забранной
    навсегда — и лист замер бы **молча**, потому что уведомление о неудаче шлёт
    `fail`, которого в этом сценарии не будет.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()

    task = (await repository.claim())[0]
    await session.commit()
    assert task.id is not None

    # Пока аренда не истекла, задача не выбирается — иначе два воркера рисовали
    # бы один лист одновременно.
    assert await repository.claim() == []

    await _expire_lease(session, task.id)

    reclaimed = await repository.claim()
    assert [item.id for item in reclaimed] == [task.id]


async def test_fresh_claim_is_not_stolen(session: AsyncSession) -> None:
    """Свежий захват держится: срок аренды с запасом перекрывает работу."""
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.BILLS)
    await session.commit()
    await repository.claim()
    await session.commit()

    assert await repository.claim() == []


async def test_terminal_failure_gets_a_long_pause(session: AsyncSession) -> None:
    """Терминальная неудача откладывает задачу надолго, но не удаляет её.

    Начинать с пяти секунд бессмысленно: ответ Google не изменится, пока не
    вмешается пользователь. Но и снять задачу нельзя — доступ могут вернуть, и
    тогда лист обязан догнать сам.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    assert spreadsheet.id is not None
    repository = SheetSyncTaskRepository(session)

    await repository.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await session.commit()
    task = (await repository.claim())[0]
    await session.commit()
    assert task.id is not None

    updated = await repository.fail(task.id, "Google вернул 403", terminal=True)
    await session.commit()

    assert updated is not None
    assert updated.attempts == 1
    assert updated.claimed_at is None
    # Пауза именно длинная, а не первая ступень экспоненты.
    assert updated.next_attempt_at is not None
    remaining = updated.next_attempt_at - datetime.now(UTC)
    assert remaining > timedelta(seconds=constants.SHEET_SYNC_RETRY_MAX_SECONDS)
    assert len(await repository.list_by_spreadsheet(spreadsheet.id)) == 1


async def _expire_lease(session: AsyncSession, task_id: int) -> None:
    """Состаривает захват задачи, как будто воркер умер давно."""
    await session.execute(
        text(
            "UPDATE sheet_sync_tasks "
            "SET claimed_at = now() - make_interval(secs => :seconds) "
            "WHERE id = :task_id"
        ),
        {"seconds": constants.SHEET_SYNC_LEASE_SECONDS + 60, "task_id": task_id},
    )
    await session.commit()
