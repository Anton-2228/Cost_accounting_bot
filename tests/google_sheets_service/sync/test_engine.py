"""Проход по очереди: порядок задач, отчёты и устойчивость к сбоям."""

from __future__ import annotations

from google_sheets_service.exceptions import GoogleApiError
from tests.google_sheets_service.factories import (
    make_category,
    make_record,
    make_source,
    make_task,
)
from tests.google_sheets_service.sync.conftest import Harness


async def test_empty_queue_does_nothing(harness: Harness) -> None:
    """Пустая очередь не порождает ни одного обращения к Google."""
    report = await harness.engine.run_once()

    assert report.claimed == 0
    assert report.status == "ok"
    assert harness.sheets.calls == []


async def test_connections_are_reset_before_every_tick(harness: Harness) -> None:
    """Пул соединений сбрасывается в начале каждого прохода.

    httplib2 не проверяет живость сокета из пула, а между проходами он успевает
    протухнуть: без сброса проход висел бы до таймаута на первом же запросе.
    """
    await harness.engine.run_once()
    await harness.engine.run_once()

    assert harness.sheets.connections_reset == 2


async def test_successful_task_is_completed(ready_harness: Harness) -> None:
    """Выполненная задача закрывается в очереди."""
    ready_harness.api.spreadsheets.categories = [make_category()]
    ready_harness.api.tasks.queue = [make_task(task_id=7, target="CATEGORIES")]

    report = await ready_harness.engine.run_once()

    assert ready_harness.api.tasks.completed == [7]
    assert report.completed == 1
    assert report.failed == 0


async def test_structure_task_needs_no_work_of_its_own(ready_harness: Harness) -> None:
    """У задачи скелета нет собственного действия.

    Всё, что ей нужно, уже сделала сверка: создала документ, листы и выдала
    доступы. Отдельная перерисовка здесь была бы работой впустую.
    """
    ready_harness.api.tasks.queue = [make_task(task_id=1, target="STRUCTURE")]

    await ready_harness.engine.run_once()

    assert ready_harness.api.tasks.completed == [1]
    # Единственное обращение к Google — чтение раскладки при сверке.
    assert ready_harness.sheets.calls == ["get_layout"]


async def test_document_structure_is_checked_once_per_tick(ready_harness: Harness) -> None:
    """Скелет сверяется один раз на документ, а не на каждую задачу.

    Это чтение из Google, и повторять его для каждого из четырёх листов значило
    бы вчетверо увеличить расход квоты без единого нового факта.
    """
    ready_harness.api.tasks.queue = [
        make_task(task_id=1, target="CATEGORIES"),
        make_task(task_id=2, target="BILLS"),
        make_task(task_id=3, target="OPERATIONS", period_id=7),
    ]

    await ready_harness.engine.run_once()

    assert ready_harness.sheets.calls.count("get_layout") == 1


async def test_tasks_of_one_document_run_in_fixed_order(ready_harness: Harness) -> None:
    """Внутри документа порядок задан: скелет, справочники, листы, чтение.

    Очередь порядка не обещает — задачи в ней независимы по построению. Но
    выполнить импорт раньше перерисовки значило бы прочитать лист, в котором
    ещё нет идентификаторов новых строк.
    """
    ready_harness.api.tasks.queue = [
        make_task(task_id=1, kind="IMPORT", target="CATEGORIES"),
        make_task(task_id=2, target="STATISTICS", period_id=7),
        make_task(task_id=3, target="CATEGORIES"),
        make_task(task_id=4, target="STRUCTURE"),
    ]

    await ready_harness.engine.run_once()

    assert ready_harness.api.tasks.completed == [4, 3, 2, 1]


async def test_one_failed_task_does_not_stop_the_others(ready_harness: Harness) -> None:
    """Задача, упавшая на Google, не мешает остальным.

    Очередь строится так, что каждая задача самодостаточна; останавливать проход
    из-за одной значило бы задерживать листы, к которым она не относится.
    """
    ready_harness.api.spreadsheets.categories = [make_category()]
    ready_harness.sheets.fail_batch_with = GoogleApiError("Слишком много", status_code=429)
    ready_harness.api.tasks.queue = [
        make_task(task_id=1, target="CATEGORIES"),
        make_task(task_id=2, target="BILLS"),
    ]

    report = await ready_harness.engine.run_once()

    assert [task_id for task_id, _, _ in ready_harness.api.tasks.failures] == [1]
    assert ready_harness.api.tasks.completed == [2]
    assert report.status == "partial"


async def test_unexpected_error_is_reported_as_non_terminal(ready_harness: Harness) -> None:
    """Незнакомая ошибка не считается терминальной.

    Терминальность — утверждение «повтор бесполезен», и делать его о том, чего
    мы не поняли, значит навсегда оставить лист неперерисованным.
    """
    ready_harness.sheets.fail_batch_with = RuntimeError("что-то пошло не так")
    ready_harness.api.tasks.queue = [make_task(task_id=1, target="CATEGORIES")]

    report = await ready_harness.engine.run_once()

    assert ready_harness.api.tasks.failures[0][2] is False
    assert report.status == "failed"


async def test_report_survives_unreachable_api(ready_harness: Harness) -> None:
    """Неудача самого отчёта не роняет проход.

    Задача останется забранной и вернётся в очередь по истечении аренды — ради
    этого срок в `claim` и появился.
    """

    async def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("api недоступно")

    ready_harness.sheets.fail_batch_with = GoogleApiError("Отказ", status_code=500)
    ready_harness.api.tasks.fail = explode  # type: ignore[method-assign]
    ready_harness.api.tasks.queue = [make_task(task_id=1, target="CATEGORIES")]

    report = await ready_harness.engine.run_once()

    assert report.failed == 1


async def test_operations_sheet_reads_deleted_catalogues(ready_harness: Harness) -> None:
    """Реестр запрашивает справочники вместе с удалёнными.

    Операция удалённой категории остаётся в реестре навсегда, и её названию
    неоткуда взяться иначе.
    """
    ready_harness.api.operations.records = [make_record()]
    ready_harness.api.spreadsheets.categories = [make_category()]
    ready_harness.api.spreadsheets.sources = [make_source()]
    ready_harness.api.tasks.queue = [make_task(target="OPERATIONS", period_id=7)]

    await ready_harness.engine.run_once()

    assert "list_categories:active=False:deleted=True" in ready_harness.api.spreadsheets.calls


async def test_statistics_sheet_reads_only_active_categories(ready_harness: Harness) -> None:
    """Строки статистики — активные категории.

    Скрытая категория выпадает из подсказок бота и из отчёта: показывать её
    пустой строкой каждый месяц незачем.
    """
    ready_harness.api.spreadsheets.categories = [make_category()]
    ready_harness.api.tasks.queue = [make_task(target="STATISTICS", period_id=7)]

    await ready_harness.engine.run_once()

    assert "list_categories:active=True:deleted=False" in ready_harness.api.spreadsheets.calls


async def test_report_counts_and_summary(ready_harness: Harness) -> None:
    """Отчёт прохода считает взятое и сделанное — это вся наблюдаемость."""
    ready_harness.api.tasks.queue = [make_task(task_id=1, target="STRUCTURE")]

    report = await ready_harness.engine.run_once()

    assert report.claimed == 1
    assert report.completed == 1
    assert "взято=1 сделано=1" in report.summary()
    assert ready_harness.engine.last_report is report


async def test_concurrent_run_is_skipped(ready_harness: Harness) -> None:
    """Повторный запуск во время прохода возвращает отметку о пропуске.

    Ручной `POST /sync` и планировщик иначе выстроились бы в очередь и сделали
    одну и ту же работу дважды подряд.
    """
    async with ready_harness.engine._lock:  # noqa: SLF001 — иначе состояние не смоделировать
        report = await ready_harness.engine.run_once()

    assert report.status == "skipped"
    assert ready_harness.api.tasks.calls == []
