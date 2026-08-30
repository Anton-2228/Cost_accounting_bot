"""Импорт: правки листа едут в базу и возвращаются в лист."""

from __future__ import annotations

from google_sheets_service.main_api.dto import ImportResult
from tests.google_sheets_service.factories import make_category, make_task
from tests.google_sheets_service.sync.conftest import Harness

CATEGORIES_RANGE = "'Categories'!A2:G"
BILLS_RANGE = "'Bills'!A2:G"


async def test_import_reads_sheet_and_sends_rows_to_api(ready_harness: Harness) -> None:
    """Лист читается и уезжает в api сырыми строками.

    Сервис не разбирает содержимое: правила уникальности имён и псевдонимов
    живут в api, и знать о них ему неоткуда.
    """
    ready_harness.sheets.values[CATEGORIES_RANGE] = [
        [1, 1, 0, 1, "Еда", "еда продукты", "выпечка"],
        ["", 1, 0, 1, "Транспорт", "транспорт", ""],
    ]
    ready_harness.api.tasks.queue = [make_task(kind="IMPORT", target="CATEGORIES")]

    await ready_harness.engine.run_once()

    target, rows = ready_harness.api.imports.received[0]
    assert target == "CATEGORIES"
    # Числовые ячейки приведены к строкам без «1.0»: иначе валидация api
    # отвергла бы каждую строку листа.
    assert rows[0] == ["1", "1", "0", "1", "Еда", "еда продукты", "выпечка"]
    # Короткая строка дополнена до ширины листа.
    assert rows[1] == ["", "1", "0", "1", "Транспорт", "транспорт", ""]


async def test_import_redraws_the_sheet_immediately(ready_harness: Harness) -> None:
    """После успешного импорта лист перерисовывается в той же задаче.

    Иначе между записью в базу и перерисовкой остаётся окно, где у новых строк
    ещё пустые идентификаторы: второй `/sync`, попавший в него, прочитал бы их
    как «создать» и завёл дубликаты категорий.
    """
    ready_harness.sheets.values[CATEGORIES_RANGE] = [["", 1, 0, 1, "Еда", "еда", ""]]
    ready_harness.api.imports.result = ImportResult(
        error=None, created=1, updated=0, deleted=0
    )
    ready_harness.api.spreadsheets.categories = [make_category()]
    ready_harness.api.tasks.queue = [make_task(task_id=1, kind="IMPORT", target="CATEGORIES")]

    await ready_harness.engine.run_once()

    # Чтение листа, затем запись в него — в пределах одной задачи.
    assert ready_harness.sheets.calls == [
        "get_layout",
        f"get_values:{CATEGORIES_RANGE}",
        "batch_update:updateCells",
    ]
    assert ready_harness.api.tasks.completed == [1]


async def test_import_error_does_not_redraw_and_is_not_a_failure(
    ready_harness: Harness,
) -> None:
    """Ошибка разбора не считается сбоем задачи.

    В базу не записано ничего, русский текст ошибки api уже положил в
    уведомления, а лист и так соответствует базе — перерисовывать нечего.
    Повторять чтение того же листа бессмысленно: он не изменится сам.
    """
    ready_harness.sheets.values[CATEGORIES_RANGE] = [["", 1, 1, 1, "Еда", "еда", ""]]
    ready_harness.api.imports.result = ImportResult(
        error="В категориях в 1 строке Income и Cost вместе",
        created=0,
        updated=0,
        deleted=0,
    )
    ready_harness.api.tasks.queue = [make_task(task_id=1, kind="IMPORT", target="CATEGORIES")]

    report = await ready_harness.engine.run_once()

    assert "batch_update:updateCells" not in ready_harness.sheets.calls
    assert ready_harness.api.tasks.completed == [1]
    assert report.failed == 0


async def test_bills_import_reads_its_own_range(ready_harness: Harness) -> None:
    """Лист счетов читается по своей ширине."""
    ready_harness.sheets.values[BILLS_RANGE] = [
        [1, 1, "Карта", "карта", "RUB", 1000.5, 850.5]
    ]
    ready_harness.api.tasks.queue = [make_task(kind="IMPORT", target="BILLS")]

    await ready_harness.engine.run_once()

    target, rows = ready_harness.api.imports.received[0]
    assert target == "BILLS"
    # Дробный остаток доезжает без потери копеек и без двоичного хвоста.
    assert rows[0] == ["1", "1", "Карта", "карта", "RUB", "1000.5", "850.5"]


async def test_import_of_empty_sheet_sends_no_rows(ready_harness: Harness) -> None:
    """Пустой лист уезжает пустым списком строк.

    Решение, что делать с пустым справочником, принимает api: у него есть
    русский текст «Добавьте хотя бы одну категорию».
    """
    ready_harness.api.tasks.queue = [make_task(kind="IMPORT", target="CATEGORIES")]

    await ready_harness.engine.run_once()

    assert ready_harness.api.imports.received[0][1] == []
