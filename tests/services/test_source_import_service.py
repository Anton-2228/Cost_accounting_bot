"""Тесты вчитывания листа `Bills`."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import NotificationKind, SheetTarget
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.source_repository import SourceRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.source_import_service import SourceImportService
from tests import factories


def _row(
    source_id: str = "",
    active: str = "1",
    name: str = "Кошелёк",
    associations: str = "",
    start_balance: str = "0",
    current_balance: str = "",
) -> list[str]:
    """Строка листа `Bills`: ID · Active · Name · Assoc · Start · Current."""
    return [source_id, active, name, associations, start_balance, current_balance]


async def test_new_row_creates_source(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Строка без ID создаёт счёт с начальным остатком."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await source_import_service.import_rows(
        spreadsheet.id,
        [_row(name="Карта", associations="сбер", start_balance="1500,50")],
    )

    assert result.error is None
    sources = await SourceRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert [source.title for source in sources] == ["Карта"]
    assert sources[0].start_balance == Decimal("1500.50")
    assert sources[0].associations == ["карта", "сбер"]


async def test_current_balance_column_is_ignored(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Колонка `Current balance` не читается: баланс вычисляется.

    Прежняя версия хранила его в БД и переписывала с листа, поэтому любое
    расхождение закреплялось навсегда.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await source_import_service.import_rows(
        spreadsheet.id,
        [_row(name="Карта", start_balance="100", current_balance="999999")],
    )

    balances = await SourceRepository(session).balances(spreadsheet.id)
    assert [item.balance for item in balances] == [Decimal("100.00")]


async def test_fractional_balance_is_accepted(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Копейки в остатке допустимы.

    Старый текст требовал целое число, а проверка стояла `float(...)`: копейки
    проходили, а сообщение врало. Деньги везде `Decimal`, ограничивать их целыми
    незачем.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await source_import_service.import_rows(
        spreadsheet.id, [_row(name="Копилка", start_balance="10.25")]
    )
    assert result.error is None


async def test_thousand_separator_from_russian_locale(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Неразрывный пробел-разделитель разрядов из таблицы с русской локалью."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await source_import_service.import_rows(
        spreadsheet.id, [_row(name="Счёт", start_balance="12 345,67")]
    )
    assert result.error is None

    sources = await SourceRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert sources[0].start_balance == Decimal("12345.67")


async def test_broken_balance_writes_nothing_and_notifies(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Не-число в остатке — ошибка разбора и уведомление, в БД ничего."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await source_import_service.import_rows(
        spreadsheet.id, [_row(name="Счёт", start_balance="много")]
    )

    assert result.error == "В источниках в 1 строке Balance не число"
    assert await SourceRepository(session).list_by_spreadsheet(spreadsheet.id) == []

    notifications = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in notifications] == [NotificationKind.IMPORT_ERROR]


async def test_successful_import_confirms_itself(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Прочитанный лист счетов подтверждается уведомлением.

    `Categories` и `Bills` — две независимые задачи импорта, и подтверждение у
    каждой своё: они выполняются по отдельности, иногда с заметной паузой.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await source_import_service.import_rows(spreadsheet.id, [_row(name="Карта")])

    notifications = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in notifications] == [NotificationKind.IMPORT_OK]
    assert "Bills" in notifications[0].text


async def test_cleared_row_deletes_source_and_frees_alias(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Очищенная строка удаляет счёт, освобождая его псевдоним."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    source = await factories.create_source(
        session, spreadsheet, title="Старый", associations=["старый"]
    )
    await session.commit()
    assert spreadsheet.id is not None and source.id is not None

    result = await source_import_service.import_rows(
        spreadsheet.id,
        [
            [str(source.id), "", "", "", "", ""],
            _row(name="Новый", associations="старый"),
        ],
    )

    assert result.error is None
    assert (result.created, result.deleted) == (1, 1)
    sources = await SourceRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert [item.title for item in sources] == ["Новый"]


async def test_import_marks_bills_and_operations_stale(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Правка счетов устаревает `Bills` и реестр: в нём печатается название счёта."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and period.id is not None

    await source_import_service.import_rows(spreadsheet.id, [_row(name="Карта")])

    tasks = await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert {task.target for task in tasks} == {SheetTarget.BILLS, SheetTarget.OPERATIONS}


async def test_empty_sheet_is_rejected(
    session: AsyncSession,
    source_import_service: SourceImportService,
) -> None:
    """Пустой лист — ошибка: без счетов система неработоспособна."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await source_import_service.import_rows(spreadsheet.id, [["", "", "", "", "", ""]])
    assert result.error == "Добавьте хотя бы один источник"
