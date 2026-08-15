"""Сверка скелета документа."""

from __future__ import annotations

import pytest

from google_sheets_service import constants
from google_sheets_service.exceptions import GoogleApiError
from google_sheets_service.google.sheets_client import SheetProperties
from tests.google_sheets_service.factories import (
    make_access,
    make_mapping,
    make_period,
    make_spreadsheet,
    make_task,
)
from tests.google_sheets_service.sync.conftest import Harness


async def test_creates_document_and_binds_it(harness: Harness) -> None:
    """У документа без Google-таблицы она создаётся и привязывается."""
    harness.api.spreadsheets.spreadsheet = make_spreadsheet(google_spreadsheet_id=None)
    harness.api.periods.periods = [make_period()]
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    assert "create_spreadsheet:Проверка" in harness.sheets.calls
    assert "set_google_id:google-new" in harness.api.spreadsheets.calls
    # Метка ставится сразу после создания: если процесс умрёт здесь, следующая
    # попытка найдёт документ по ней и не создаст второй.
    assert harness.drive.calls == ["find:1", "mark:google-new=1"]


async def test_does_not_create_second_document_when_marked_one_exists(
    harness: Harness,
) -> None:
    """Документ с меткой находится и привязывается вместо создания нового.

    Так закрывается сценарий, из-за которого старая версия плодила сирот:
    таблица создана, ответ api потерян, повтор задачи заводит вторую, а первая —
    уже расшаренная пользователю — остаётся никому не известной.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet(google_spreadsheet_id=None)
    harness.api.periods.periods = [make_period()]
    harness.drive.known_files["1"] = "google-existing"
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    assert "create_spreadsheet:Проверка" not in harness.sheets.calls
    assert "set_google_id:google-existing" in harness.api.spreadsheets.calls


async def test_creates_four_sheets_for_open_period(harness: Harness) -> None:
    """Новому документу заводятся справочники и оба листа открытого периода."""
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = [make_period()]
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    titles = [sheet.title for sheet in harness.sheets.layout]
    assert titles == [
        constants.CATEGORIES_SHEET_TITLE,
        constants.BILLS_SHEET_TITLE,
        "2026-08-01",
        "Stat. 2026-08-01",
    ]
    assert harness.api.sheet_mappings.calls.count("list_mappings") == 1
    assert len([call for call in harness.api.sheet_mappings.calls if "upsert" in call]) == 4


async def test_skips_sheets_of_closed_periods(harness: Harness) -> None:
    """Закрытому периоду листы не заводятся.

    По закрытому периоду api больше не ставит перерисовку, и пустая вкладка за
    позапрошлый месяц осталась бы пустой навсегда.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = [
        make_period(period_id=6, status="CLOSED"),
        make_period(period_id=7, status="OPEN"),
    ]
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    assert len(harness.sheets.layout) == 4


async def test_recreates_sheet_deleted_by_user(harness: Harness) -> None:
    """Удалённая пользователем вкладка создаётся заново.

    Соответствие указывает в пустоту, и перерисовка по нему получала бы отказ
    Google на каждой попытке до скончания века.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = []
    harness.api.sheet_mappings.mappings = [
        make_mapping(target="CATEGORIES", google_sheet_id=11, title="Categories"),
        make_mapping(mapping_id=2, target="BILLS", google_sheet_id=12, title="Bills"),
    ]
    # В документе остался только один лист: второй пользователь удалил.
    harness.sheets.layout = [
        SheetProperties(sheet_id=11, title="Categories", row_count=200, column_count=7)
    ]
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    recreated = [sheet.title for sheet in harness.sheets.layout]
    assert recreated.count(constants.BILLS_SHEET_TITLE) == 1
    assert "upsert_mapping:BILLS:None" in harness.api.sheet_mappings.calls


async def test_grants_pending_accesses(harness: Harness) -> None:
    """Невыданные доступы выдаются и отмечаются выданными."""
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = []
    harness.api.spreadsheets.pending_accesses = [make_access(access_id=5, email="a@example.com")]
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    assert harness.drive.granted == ["a@example.com"]
    assert harness.api.spreadsheets.granted_ids == [5]


async def test_bad_email_does_not_fail_the_whole_task(harness: Harness) -> None:
    """Отказ по конкретной почте не валит сверку.

    Иначе одна опечатка в адресе навечно заблокировала бы создание листов новых
    месяцев.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = []
    harness.api.spreadsheets.pending_accesses = [
        make_access(access_id=5, email="broken"),
        make_access(access_id=6, email="good@example.com"),
    ]
    harness.drive.reject_emails = {"broken"}
    harness.api.tasks.queue = [make_task(task_id=1, target="STRUCTURE")]

    report = await harness.engine.run_once()

    assert harness.api.spreadsheets.failed_ids == [5]
    assert harness.api.spreadsheets.granted_ids == [6]
    assert report.completed == 1
    assert report.failed == 0


async def test_structure_failure_fails_every_task_of_document(harness: Harness) -> None:
    """Провал сверки проваливает все задачи документа.

    Без документа и листов ни одна из них выполнима не будет, и пробовать их по
    очереди значило бы четыре раза получить один и тот же отказ.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = [make_period()]
    harness.sheets.fail_batch_with = GoogleApiError("Нет доступа", status_code=403)
    harness.api.tasks.queue = [
        make_task(task_id=1, target="CATEGORIES"),
        make_task(task_id=2, target="BILLS"),
    ]

    report = await harness.engine.run_once()

    assert report.failed == 2
    assert [task_id for task_id, _, _ in harness.api.tasks.failures] == [1, 2]
    # 403 повтором не лечится: пользователь узнает об этом сразу.
    assert all(terminal for _, _, terminal in harness.api.tasks.failures)


@pytest.mark.parametrize(
    ("status", "expected_terminal"),
    [(403, True), (404, True), (400, True), (429, False), (500, False), (None, False)],
)
async def test_terminal_flag_follows_google_status(
    ready_harness: Harness,
    status: int | None,
    expected_terminal: bool,
) -> None:
    """Терминальность определяется кодом ответа Google, а не числом попыток.

    «Доступ отозван» не станет успешным ни на десятой попытке, ни на сотой, а
    «слишком много запросов» пройдёт само.
    """
    ready_harness.sheets.fail_batch_with = GoogleApiError("Отказ", status_code=status)
    ready_harness.api.tasks.queue = [make_task(task_id=1, target="CATEGORIES")]

    await ready_harness.engine.run_once()

    assert ready_harness.api.tasks.failures[0][2] is expected_terminal


async def test_document_is_created_with_catalogue_sheets(harness: Harness) -> None:
    """Справочники заводятся сразу в теле создания документа.

    Документ без явного списка листов Google создаёт со своим «Лист1» на тысячу
    строк и двадцать шесть колонок. В `sheet_mappings` его нет, удалять чужие
    листы сверка не должна — и он остался бы первой вкладкой навсегда.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet(google_spreadsheet_id=None)
    harness.api.periods.periods = []
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    titles = [sheet.title for sheet in harness.sheets.layout]
    assert titles == [constants.CATEGORIES_SHEET_TITLE, constants.BILLS_SHEET_TITLE]
    # Ни одного `addSheet`: оба листа приехали вместе с документом.
    assert not any("addSheet" in kinds for kinds in harness.sheets.calls)


async def test_created_catalogue_sheets_are_registered_and_formatted(
    harness: Harness,
) -> None:
    """Листы, приехавшие вместе с документом, оформляются и запоминаются."""
    harness.api.spreadsheets.spreadsheet = make_spreadsheet(google_spreadsheet_id=None)
    harness.api.periods.periods = []
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    assert "upsert_mapping:CATEGORIES:None" in harness.api.sheet_mappings.calls
    assert "upsert_mapping:BILLS:None" in harness.api.sheet_mappings.calls
    protections = [
        request
        for batch in harness.sheets.batches
        for request in batch
        if "addProtectedRange" in request
    ]
    assert protections, "листы должны получить защиты"


async def test_existing_sheet_is_adopted_instead_of_recreated(harness: Harness) -> None:
    """Лист, существующий в документе, подхватывается, а не создаётся заново.

    Так выглядит повтор после сбоя между созданием листа и записью о нём.
    Заголовки листов уникальны: попытка создать второй `Categories` получила бы
    отказ Google, и документ стало бы нечем починить.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = []
    # Лист в документе есть, а записи о нём нет.
    harness.sheets.layout = [
        SheetProperties(sheet_id=55, title="Categories", row_count=200, column_count=7)
    ]
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    assert [sheet.title for sheet in harness.sheets.layout].count("Categories") == 1
    upserts = [call for call in harness.api.sheet_mappings.calls if "upsert" in call]
    assert "upsert_mapping:CATEGORIES:None" in upserts


async def test_adopted_sheet_does_not_accumulate_protections(harness: Harness) -> None:
    """Повторное оформление снимает прежние защиты, а не кладёт вторые поверх.

    `addProtectedRange` не идемпотентен, и без снятия каждая сверка добавляла бы
    документу ещё один слой защит — без предела.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = []
    harness.sheets.layout = [
        SheetProperties(
            sheet_id=55,
            title="Categories",
            row_count=200,
            column_count=7,
            protected_range_ids=(901, 902),
        )
    ]
    harness.api.tasks.queue = [make_task(target="STRUCTURE")]

    await harness.engine.run_once()

    deleted = [
        request["deleteProtectedRange"]["protectedRangeId"]
        for batch in harness.sheets.batches
        for request in batch
        if "deleteProtectedRange" in request
    ]
    assert deleted == [901, 902]


async def test_sheet_of_closed_period_is_restored_when_a_task_needs_it(
    harness: Harness,
) -> None:
    """Вкладка закрытого месяца восстанавливается, если по ней есть задача.

    Ролловер, закрывая месяц, напоследок его перерисовывает — пользователь мог
    добавить операцию в последние минуты. Удали он к тому времени вкладку,
    задача не нашла бы листа; терминальной такая ошибка не считается, поэтому
    она повторялась бы вечно, шлёпая уведомление каждые пять попыток.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = [make_period(period_id=6, status="CLOSED")]
    harness.api.sheet_mappings.mappings = [
        make_mapping(target="CATEGORIES", google_sheet_id=11, title="Categories"),
        make_mapping(mapping_id=2, target="BILLS", google_sheet_id=12, title="Bills"),
    ]
    harness.sheets.layout = [
        SheetProperties(sheet_id=11, title="Categories", row_count=200, column_count=7),
        SheetProperties(sheet_id=12, title="Bills", row_count=200, column_count=6),
    ]
    harness.api.tasks.queue = [
        make_task(task_id=1, target="OPERATIONS", period_id=6),
    ]

    report = await harness.engine.run_once()

    assert "2026-08-01" in [sheet.title for sheet in harness.sheets.layout]
    assert report.completed == 1
    assert report.failed == 0


async def test_closed_period_without_tasks_gets_no_sheets(harness: Harness) -> None:
    """Период, о котором никто не спрашивал, листов не получает.

    Иначе документ, привязанный спустя годы, оброс бы пустыми вкладками за всю
    историю — их никто никогда не заполнит, а место в документе они займут.
    """
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = [
        make_period(period_id=5, status="CLOSED"),
        make_period(period_id=6, status="CLOSED"),
        make_period(period_id=7, status="OPEN"),
    ]
    harness.api.tasks.queue = [make_task(task_id=1, target="STRUCTURE")]

    await harness.engine.run_once()

    titles = [sheet.title for sheet in harness.sheets.layout]
    # Только справочники и листы единственного открытого периода.
    assert len(titles) == 4
