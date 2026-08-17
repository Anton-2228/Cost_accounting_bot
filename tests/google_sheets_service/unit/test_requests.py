"""Сборка тел запросов из описания листа."""

from __future__ import annotations

from typing import Any

from google_sheets_service import constants
from google_sheets_service.sheets import requests, values
from google_sheets_service.sheets.layout import SheetPayload
from google_sheets_service.sheets.layouts import (
    BILLS_LAYOUT,
    CATEGORIES_LAYOUT,
    OPERATIONS_LAYOUT,
)

SHEET_ID = 42


def _payload(rows: int, width: int = CATEGORIES_LAYOUT.column_count) -> SheetPayload:
    """Содержимое из указанного числа одинаковых строк."""
    return SheetPayload(rows=[[values.text_cell("x")] * width for _ in range(rows)])


def _kinds(batch: list[dict[str, Any]]) -> list[str]:
    """Виды запросов пачки по порядку."""
    return [next(iter(request)) for request in batch]


def test_create_sheet_adds_spare_columns_to_the_grid() -> None:
    """Сетка шире раскладки ровно на запас под формулы пользователя.

    Умолчание Google в 26 колонок съедало лимит документа в десять миллионов
    ячеек, поэтому сетка остаётся считанной; но лист точно по раскладке не
    оставлял пользователю ни одной ячейки под собственную формулу.
    """
    request = requests.create_sheet_request("Categories", CATEGORIES_LAYOUT)
    grid = request["addSheet"]["properties"]["gridProperties"]
    assert CATEGORIES_LAYOUT.column_count == 7
    assert grid["columnCount"] == 7 + constants.SPARE_COLUMN_COUNT
    assert grid["frozenRowCount"] == constants.HEADER_ROW_COUNT


def test_header_requests_protect_id_and_current_balance() -> None:
    """Колонки, которые заполняет система, закрываются от правки.

    У листа счетов таких две: идентификатор и вычисляемый баланс.
    """
    batch = requests.header_requests(SHEET_ID, BILLS_LAYOUT)
    protections = [item["addProtectedRange"] for item in batch if "addProtectedRange" in item]
    descriptions = [item["protectedRange"]["description"] for item in protections]
    assert "Заголовки" in descriptions
    assert "Колонка «ID»" in descriptions
    assert "Колонка «Current balance»" in descriptions
    # Пустой список редакторов означает «править может только владелец файла».
    assert all(item["protectedRange"]["editors"] == {"users": []} for item in protections)


def test_header_requests_protect_operations_system_columns_only() -> None:
    """Реестр закрывается по системным колонкам, а не листом целиком.

    Он производен от базы, и правка в нём была бы потеряна следующей же
    перерисовкой. Но защита листом целиком (`{"sheetId": ...}`) закрыла бы и
    свободные колонки, ради которых запас и появился.
    """
    batch = requests.header_requests(SHEET_ID, OPERATIONS_LAYOUT)
    protections = [item["addProtectedRange"] for item in batch if "addProtectedRange" in item]
    assert len(protections) == 1
    assert protections[0]["protectedRange"]["range"] == {
        "sheetId": SHEET_ID,
        "startRowIndex": 0,
        "startColumnIndex": 0,
        "endColumnIndex": OPERATIONS_LAYOUT.column_count,
    }


def test_redraw_never_touches_spare_columns() -> None:
    """Ни данные, ни затирание хвоста не выходят за системные колонки.

    Это и есть условие, при котором формула пользователя переживает
    перерисовку: границей всех запросов служит `column_count`, а не ширина
    сетки.
    """
    batch = requests.redraw_requests(
        SHEET_ID,
        OPERATIONS_LAYOUT,
        _payload(rows=2, width=OPERATIONS_LAYOUT.column_count),
        sheet_row_count=200,
    )
    ends = [item["updateCells"]["range"]["endColumnIndex"] for item in batch]
    assert ends == [OPERATIONS_LAYOUT.column_count] * 2
    assert OPERATIONS_LAYOUT.column_count < OPERATIONS_LAYOUT.grid_column_count


def test_column_widths_are_merged_for_equal_neighbours() -> None:
    """Соседние колонки одной ширины склеиваются в один запрос.

    У листа статистики их три десятка по 45 пикселей.
    """
    batch = requests.header_requests(SHEET_ID, CATEGORIES_LAYOUT)
    widths = [item for item in batch if "updateDimensionProperties" in item]
    # ID(50) · Active+Income+Cost(100) · Name(200) · Associations(300) · Types(400)
    assert len(widths) == 5
    second = widths[1]["updateDimensionProperties"]
    assert second["range"]["startIndex"] == 1
    assert second["range"]["endIndex"] == 4
    assert second["properties"]["pixelSize"] == 100


def test_redraw_writes_data_and_clears_tail() -> None:
    """Перерисовка пишет данные и затирает всё, что было ниже.

    Без затирания удаление операции оставило бы последнюю строку на месте:
    новых данных на неё не пришло, а старые никто не стёр.
    """
    batch = requests.redraw_requests(
        SHEET_ID,
        CATEGORIES_LAYOUT,
        _payload(rows=2),
        sheet_row_count=200,
    )
    assert _kinds(batch) == ["updateCells", "updateCells"]

    data, tail = batch[0]["updateCells"], batch[1]["updateCells"]
    assert data["range"]["startRowIndex"] == constants.HEADER_ROW_COUNT
    assert data["range"]["endRowIndex"] == constants.HEADER_ROW_COUNT + 2
    assert tail["range"]["startRowIndex"] == constants.HEADER_ROW_COUNT + 2
    assert tail["range"]["endRowIndex"] == 200
    # У хвоста нет `rows`: пустой набор полей и есть стирание.
    assert "rows" not in tail
    assert tail["fields"] == "userEnteredValue"


def test_redraw_of_empty_sheet_clears_everything() -> None:
    """Лист, из которого удалили всё, затирается целиком."""
    batch = requests.redraw_requests(
        SHEET_ID,
        CATEGORIES_LAYOUT,
        SheetPayload(),
        sheet_row_count=200,
    )
    assert _kinds(batch) == ["updateCells"]
    assert batch[0]["updateCells"]["range"]["startRowIndex"] == constants.HEADER_ROW_COUNT


def test_redraw_grows_grid_when_rows_do_not_fit() -> None:
    """Сетка наращивается, когда операций стало больше, чем строк.

    Это снимает потолок старой версии в 999 операций за месяц, о который она
    разбивалась молча.
    """
    batch = requests.redraw_requests(
        SHEET_ID,
        CATEGORIES_LAYOUT,
        _payload(rows=250),
        sheet_row_count=200,
    )
    assert _kinds(batch)[0] == "appendDimension"
    # Растём кусками, а не ровно по надобности: иначе запрос уходил бы почти
    # на каждую перерисовку.
    assert batch[0]["appendDimension"]["length"] == constants.GRID_ROW_CHUNK


def test_redraw_appends_data_dependent_formatting_last() -> None:
    """Оформление, зависящее от данных, идёт после самих данных."""
    payload = SheetPayload(
        rows=[[values.text_cell("x")]],
        extra_requests=[{"repeatCell": {}}],
    )
    batch = requests.redraw_requests(
        SHEET_ID, CATEGORIES_LAYOUT, payload, sheet_row_count=200
    )
    assert _kinds(batch)[-1] == "repeatCell"
