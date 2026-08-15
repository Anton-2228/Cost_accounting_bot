"""Тесты жизненного цикла учётной таблицы."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.core.period import now_in_timezone
from api.enums import NotificationKind, SheetTarget, SyncTaskKind
from api.exceptions.base import ConflictError, NotFoundError
from api.repositories.category_repository import CategoryRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_access_repository import SpreadsheetAccessRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.repositories.user_repository import UserRepository
from api.services.spreadsheet_service import SpreadsheetService
from tests import factories


async def test_create_builds_whole_document_in_one_transaction(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Создание даёт пользователя, период, две категории и задачу STRUCTURE.

    Google-таблицы при этом нет: api в Google не ходит, а ставит задачу. Прежний
    код создавал таблицу в Google до записи в БД, и падение БД оставляло
    осиротевший документ, о котором никто уже не знал.
    """
    spreadsheet = await spreadsheet_service.create(
        telegram_id=555,
        title="Мои расходы",
        reset_day=10,
    )

    assert spreadsheet.id is not None
    assert spreadsheet.google_spreadsheet_id is None

    assert await UserRepository(session).get_by_telegram_id(555) is not None
    assert len(await PeriodRepository(session).list_by_spreadsheet(spreadsheet.id)) == 1

    categories = await CategoryRepository(session).list_by_spreadsheet(spreadsheet.id)
    titles = {category.title for category in categories}
    assert titles == {constants.DEFAULT_INCOME_CATEGORY, constants.DEFAULT_EXPENSE_CATEGORY}
    # Псевдоним по умолчанию — само название в нижнем регистре: иначе категорию
    # нельзя было бы указать её собственным именем.
    for category in categories:
        assert category.title.lower() in category.associations

    tasks = await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert [(task.kind, task.target) for task in tasks] == [
        (SyncTaskKind.REDRAW, SheetTarget.STRUCTURE)
    ]


async def test_create_with_email_leaves_access_pending(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Почта запоминается со статусом «выдать предстоит»: выдаёт доступ gsheets."""
    spreadsheet = await spreadsheet_service.create(
        telegram_id=556,
        title="Мои расходы",
        reset_day=10,
        email="user@example.com",
    )

    assert spreadsheet.id is not None
    pending = await SpreadsheetAccessRepository(session).list_pending(spreadsheet.id)
    assert [access.email for access in pending] == ["user@example.com"]


async def test_second_start_is_conflict(spreadsheet_service: SpreadsheetService) -> None:
    """Повторный /start не создаёт вторую таблицу.

    В старой версии ничто не мешало одному пользователю набрать несколько
    таблиц, после чего запрос по telegram_id выбирал одну из них произвольно.
    """
    await spreadsheet_service.create(telegram_id=557, title="Первая", reset_day=1)

    with pytest.raises(ConflictError):
        await spreadsheet_service.create(telegram_id=557, title="Вторая", reset_day=1)


async def test_set_google_id_notifies_and_redraws(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Появление документа даёт уведомление и перерисовку всех листов.

    К этому моменту в БД уже есть категории, а возможно и операции, сделанные до
    создания таблицы, — их надо перенести на листы целиком.
    """
    spreadsheet = await spreadsheet_service.create(telegram_id=558, title="Т", reset_day=5)
    assert spreadsheet.id is not None

    updated = await spreadsheet_service.set_google_id(spreadsheet.id, "google-abc")
    assert updated.google_spreadsheet_id == "google-abc"

    notifications = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in notifications] == [NotificationKind.TABLE_READY]
    assert "google-abc" in notifications[0].text

    targets = {
        task.target
        for task in await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    }
    assert {SheetTarget.CATEGORIES, SheetTarget.BILLS, SheetTarget.OPERATIONS} <= targets


async def test_set_google_id_is_idempotent_but_rejects_another_document(
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Тот же идентификатор — можно, другой — 409.

    Повтор возможен буднично: gsheets создал документ и потерял ответ. А вот
    подмена оставила бы пользователя с таблицей, в которой ничего нет.
    """
    spreadsheet = await spreadsheet_service.create(telegram_id=559, title="Т", reset_day=5)
    assert spreadsheet.id is not None

    await spreadsheet_service.set_google_id(spreadsheet.id, "google-1")
    again = await spreadsheet_service.set_google_id(spreadsheet.id, "google-1")
    assert again.google_spreadsheet_id == "google-1"

    with pytest.raises(ConflictError):
        await spreadsheet_service.set_google_id(spreadsheet.id, "google-2")


async def test_document_without_google_table_refuses_work(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Пока таблицы нет, работать с ней нельзя: 409 со внятной причиной.

    Операция, принятая «вслепую», выглядела бы для пользователя потерянной:
    смотреть ему пока некуда.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    with pytest.raises(ConflictError) as info:
        await spreadsheet_service.add_access(spreadsheet.id, "user@example.com")
    assert info.value.details == {"reason": "spreadsheet_not_ready"}


async def test_add_access_enqueues_structure_and_rejects_duplicate(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Доступ ставит задачу STRUCTURE, повтор той же почты — 409."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await spreadsheet_service.add_access(spreadsheet.id, "a@example.com")
    tasks = await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert [task.target for task in tasks] == [SheetTarget.STRUCTURE]

    with pytest.raises(ConflictError):
        await spreadsheet_service.add_access(spreadsheet.id, "a@example.com")


async def test_mark_access_granted(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Выданный доступ уходит из списка ожидающих."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    access = await spreadsheet_service.add_access(spreadsheet.id, "b@example.com")
    assert access.id is not None
    assert access.granted_at is None

    await spreadsheet_service.mark_access_granted(spreadsheet.id, access.id)
    assert await spreadsheet_service.list_pending_accesses(spreadsheet.id) == []

    with pytest.raises(NotFoundError):
        await spreadsheet_service.mark_access_granted(spreadsheet.id, access.id + 1000)


async def test_request_import_asks_for_both_sheets(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Команда /sync ставит две задачи IMPORT — по листу на справочник.

    Бот не имеет доступа к Google API, поэтому просьба доезжает до gsheets
    единственным доступным каналом: этой же очередью.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await spreadsheet_service.request_import(spreadsheet.id)

    tasks = await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert {(task.kind, task.target) for task in tasks} == {
        (SyncTaskKind.IMPORT, SheetTarget.CATEGORIES),
        (SyncTaskKind.IMPORT, SheetTarget.BILLS),
    }


async def test_import_and_redraw_of_one_sheet_do_not_collapse(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Импорт и перерисовка одного листа — разные задачи.

    Направление входит в уникальный ключ: схлопнись они в одну строку, одна из
    двух работ потерялась бы совсем.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    tasks = SheetSyncTaskRepository(session)
    await tasks.enqueue(spreadsheet.id, SheetTarget.CATEGORIES)
    await spreadsheet_service.request_import(spreadsheet.id)

    kinds = {
        (task.kind, task.target)
        for task in await tasks.list_by_spreadsheet(spreadsheet.id)
        if task.target is SheetTarget.CATEGORIES
    }
    assert kinds == {
        (SyncTaskKind.REDRAW, SheetTarget.CATEGORIES),
        (SyncTaskKind.IMPORT, SheetTarget.CATEGORIES),
    }


async def test_delete_removes_document_with_owner(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Удаление документа сносит и пользователя, и всё содержимое.

    Каскад проходит целиком благодаря отложенным составным ключам: порядок между
    каскадами не определён, и немедленная проверка уронила бы удаление.
    """
    spreadsheet = await spreadsheet_service.create(telegram_id=560, title="Т", reset_day=5)
    assert spreadsheet.id is not None

    await spreadsheet_service.delete(spreadsheet.id)

    assert await UserRepository(session).get_by_telegram_id(560) is None
    with pytest.raises(NotFoundError):
        await spreadsheet_service.get(spreadsheet.id)
    assert await CategoryRepository(session).list_by_spreadsheet(spreadsheet.id) == []


async def test_get_by_telegram_id_of_unknown_user(
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Незнакомый пользователь — 404, а не пустой ответ."""
    with pytest.raises(NotFoundError):
        await spreadsheet_service.get_by_telegram_id(999_999)


async def test_deleted_catalogues_are_available_on_demand(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """Удалённые категории и счета отдаются по запросу.

    Удаление мягкое, а операции удалённой категории остаются в реестре навсегда.
    Без этого у архивного листа неоткуда взять название в колонках `Category` и
    `Source`: осталась бы пустая ячейка у операции, которая точно была.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Былое")
    source = await factories.create_source(session, spreadsheet, title="Закрытый")
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    moment = now_in_timezone(spreadsheet.timezone)
    assert await CategoryRepository(session).soft_delete(category.id, at=moment)
    assert await SourceRepository(session).soft_delete(source.id, at=moment)
    await session.commit()

    assert await spreadsheet_service.list_categories(spreadsheet.id) == []
    assert await spreadsheet_service.list_sources(spreadsheet.id) == []

    categories = await spreadsheet_service.list_categories(
        spreadsheet.id, include_deleted=True
    )
    sources = await spreadsheet_service.list_sources(spreadsheet.id, include_deleted=True)
    assert [item.title for item in categories] == ["Былое"]
    assert [item.title for item in sources] == ["Закрытый"]


async def test_balances_ignore_deleted_sources(
    session: AsyncSession,
    spreadsheet_service: SpreadsheetService,
) -> None:
    """А вот в балансах удалённого счёта нет: счёта больше не существует.

    Название для архива — это история, а баланс — текущее состояние, и
    показывать остаток закрытого счёта значило бы предлагать им пользоваться.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    source = await factories.create_source(session, spreadsheet, title="Закрытый")
    await session.commit()
    assert spreadsheet.id is not None and source.id is not None

    assert await SourceRepository(session).soft_delete(
        source.id, at=now_in_timezone(spreadsheet.timezone)
    )
    await session.commit()

    assert await spreadsheet_service.list_balances(spreadsheet.id) == []
