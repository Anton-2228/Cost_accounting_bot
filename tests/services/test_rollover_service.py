"""Тесты смены учётного месяца."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import period_bounds, today_in_timezone
from api.enums import NotificationKind, PeriodStatus, SheetTarget
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.category_import_service import CategoryImportService
from api.services.rollover_service import RolloverService
from tests import factories

_TIMEZONE = "Europe/Moscow"
_RESET_DAY = 15


async def test_nothing_to_do_when_current_period_is_open(
    session: AsyncSession,
    rollover_service: RolloverService,
) -> None:
    """Пока текущий период идёт, ролловер ничего не меняет.

    Идемпотентность — главное свойство: он выполняется каждую минуту.
    """
    spreadsheet = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await factories.create_period(session, spreadsheet, day=today_in_timezone(_TIMEZONE))
    await session.commit()

    assert await rollover_service.run_once() == 0


async def test_first_period_is_created_when_missing(
    session: AsyncSession,
    rollover_service: RolloverService,
) -> None:
    """Документ без периода получает текущий.

    Обычно первый период создаётся вместе с документом, но документ мог
    появиться в обход сервиса — без периода он неработоспособен.
    """
    spreadsheet = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await session.commit()
    assert spreadsheet.id is not None

    assert await rollover_service.run_once() == 1

    periods = await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id)
    today = today_in_timezone(_TIMEZONE)
    assert len(periods) == 1
    assert periods[0].contains(today)
    assert periods[0].status is PeriodStatus.OPEN


async def test_three_missed_months_are_caught_up_and_closed(
    session: AsyncSession,
    rollover_service: RolloverService,
) -> None:
    """Отставание в три месяца догоняется целиком, старые периоды закрываются.

    Прежний ролловер сравнивал `today != end_date` точным равенством: простой в
    день сброса означал безвозвратно пропущенный месяц.
    """
    spreadsheet = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await session.commit()
    assert spreadsheet.id is not None

    today = today_in_timezone(_TIMEZONE)
    stale_start, stale_end = period_bounds(today - timedelta(days=95), _RESET_DAY)
    await PeriodRepository(session).ensure(spreadsheet.id, stale_start, stale_end)
    await session.commit()

    assert await rollover_service.run_once() == 1

    periods = await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert len(periods) >= 4
    assert [period.start_date for period in periods] == sorted(
        period.start_date for period in periods
    )
    # Все закончившиеся закрыты, текущий — открыт, и он ровно один.
    open_periods = [period for period in periods if period.status is PeriodStatus.OPEN]
    assert len(open_periods) == 1
    assert open_periods[0].contains(today)
    for period in periods:
        if period.status is PeriodStatus.CLOSED:
            assert period.end_date <= today
            assert period.closed_at is not None


async def test_rollover_enqueues_structure_and_new_period_sheets(
    session: AsyncSession,
    rollover_service: RolloverService,
) -> None:
    """Новому периоду нужны листы: STRUCTURE их создаёт, REDRAW наполняет."""
    spreadsheet = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await session.commit()
    assert spreadsheet.id is not None

    today = today_in_timezone(_TIMEZONE)
    previous_start, previous_end = period_bounds(today - timedelta(days=40), _RESET_DAY)
    await PeriodRepository(session).ensure(spreadsheet.id, previous_start, previous_end)
    await session.commit()

    await rollover_service.run_once()

    tasks = await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert {task.target for task in tasks} == {
        SheetTarget.STRUCTURE,
        SheetTarget.OPERATIONS,
        SheetTarget.STATISTICS,
        SheetTarget.BILLS,
    }


async def test_rollover_notifies_about_new_period(
    session: AsyncSession,
    rollover_service: RolloverService,
) -> None:
    """О начале нового месяца пользователю сообщают."""
    spreadsheet = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await session.commit()
    assert spreadsheet.id is not None

    await rollover_service.run_once()

    notifications = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in notifications] == [NotificationKind.ROLLOVER]


async def test_second_run_changes_nothing(
    session: AsyncSession,
    rollover_service: RolloverService,
) -> None:
    """Повторный проход идемпотентен: уникальный ключ периода не даст дубля."""
    spreadsheet = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await session.commit()
    assert spreadsheet.id is not None

    assert await rollover_service.run_once() == 1
    before = await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id)

    assert await rollover_service.run_once() == 0
    after = await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert [period.id for period in before] == [period.id for period in after]


async def test_one_broken_document_does_not_stop_the_others(
    session: AsyncSession,
    rollover_service: RolloverService,
) -> None:
    """Документ с несуществующим часовым поясом не мешает остальным.

    Иначе ролловер встал бы навсегда, повторяя одно и то же падение каждый проход.
    """
    broken = await factories.create_spreadsheet(session, ready=True, timezone="Europe/Нигде")
    healthy = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await session.commit()
    assert broken.id is not None and healthy.id is not None

    assert await rollover_service.run_once() == 1

    periods = PeriodRepository(session)
    assert await periods.list_by_spreadsheet(broken.id) == []
    assert len(await periods.list_by_spreadsheet(healthy.id)) == 1


async def test_closed_period_is_not_redrawn_by_later_edits(
    session: AsyncSession,
    rollover_service: RolloverService,
    category_import_service: CategoryImportService,
) -> None:
    """Закрытый период выпадает из веера задач.

    Ради этого период и закрывается: иначе через два года одна правка
    справочника перерисовывала бы все месяцы за всю историю документа.
    """
    spreadsheet = await factories.create_spreadsheet(
        session, ready=True, reset_day=_RESET_DAY, timezone=_TIMEZONE
    )
    await session.commit()
    assert spreadsheet.id is not None

    today = today_in_timezone(_TIMEZONE)
    old_start, old_end = period_bounds(today - timedelta(days=70), _RESET_DAY)
    periods = PeriodRepository(session)
    old_period = await periods.ensure(spreadsheet.id, old_start, old_end)
    await session.commit()
    assert old_period.id is not None

    await rollover_service.run_once()

    # Очередь опустошаем, чтобы дальше видеть только задачи, поставленные правкой.
    tasks = SheetSyncTaskRepository(session)
    for task in await tasks.list_by_spreadsheet(spreadsheet.id):
        assert task.id is not None and task.requested_at is not None
        assert await tasks.complete(task.id, task.requested_at)
    await session.commit()

    await category_import_service.import_rows(
        spreadsheet.id,
        [["", "1", "0", "1", "Еда", "", ""]],
    )

    affected_periods = {
        task.period_id
        for task in await tasks.list_by_spreadsheet(spreadsheet.id)
        if task.period_id is not None
    }
    assert old_period.id not in affected_periods
