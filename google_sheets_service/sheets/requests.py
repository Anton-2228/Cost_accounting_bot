"""Сборка тел запросов `spreadsheets.batchUpdate` из описания листа.

Чистый модуль: на вход — описание и данные, на выход — список запросов. Ни
одного обращения к сети, поэтому проверяется обычными тестами на равенство.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from google_sheets_service import constants
from google_sheets_service.sheets import values
from google_sheets_service.sheets.a1 import grid_range
from google_sheets_service.sheets.layout import (
    DATE_HEADER_ROTATION,
    HEADER_BACKGROUND,
    HEADER_FONT_SIZE,
    SheetLayout,
    SheetPayload,
)


def sheet_properties(
    title: str,
    layout: SheetLayout,
    *,
    row_count: int = constants.GRID_INITIAL_ROWS,
) -> dict[str, Any]:
    """Свойства листа: сетка по раскладке плюс запас, замороженная шапка.

    Старая версия оставляла умолчание в 26 колонок и 1000 строк: лишние ячейки
    съедали лимит документа в десять миллионов, а тысяча строк была потолком в
    999 операций за месяц, о который система разбивалась молча.

    Ширина — `grid_column_count`, а не `column_count`: десять колонок за
    системными отданы пользователю под собственные формулы. Перерисовка их не
    трогает, потому что все её запросы ограничены `column_count`.
    """
    return {
        "title": title,
        "gridProperties": {
            "rowCount": max(row_count, constants.FIRST_DATA_ROW),
            "columnCount": layout.grid_column_count,
            "frozenRowCount": constants.HEADER_ROW_COUNT,
        },
    }


def create_sheet_request(
    title: str,
    layout: SheetLayout,
    *,
    row_count: int = constants.GRID_INITIAL_ROWS,
) -> dict[str, Any]:
    """Запрос на добавление листа в существующий документ."""
    return {"addSheet": {"properties": sheet_properties(title, layout, row_count=row_count)}}


def header_requests(
    sheet_id: int,
    layout: SheetLayout,
    *,
    existing_protection_ids: Sequence[int] = (),
) -> list[dict[str, Any]]:
    """Запросы, оформляющие лист: ширины, шапка, выравнивание тела и защиты.

    Идемпотентны целиком. Само по себе это неверно для `addProtectedRange` — он
    на второй раз кладёт вторую защиту поверх первой, — поэтому уже наложенные
    защиты сначала снимаются. Без этого повторное оформление (лист есть, а
    запись о нём в `sheet_mappings` потерялась) плодило бы их без предела.
    """
    requests: list[dict[str, Any]] = [
        _header_row_request(sheet_id, layout),
        _body_alignment_request(sheet_id, layout),
    ]
    requests.extend(_column_width_requests(sheet_id, layout))
    requests.extend(
        {"deleteProtectedRange": {"protectedRangeId": item}}
        for item in existing_protection_ids
    )
    requests.extend(_protection_requests(sheet_id, layout))
    return requests


def redraw_requests(
    sheet_id: int,
    layout: SheetLayout,
    payload: SheetPayload,
    *,
    sheet_row_count: int,
) -> list[dict[str, Any]]:
    """Запросы одной перерисовки: данные, затирание хвоста, зависимое оформление.

    Возвращается одним списком и отправляется одним `batchUpdate` — а тот
    атомарен. Поэтому состояния «данные стёрли, а новые записать не успели» не
    существует; старая версия получала его при любом сбое между `values.clear` и
    `values.batchUpdate`, и пользователь видел пустой лист.
    """
    requests: list[dict[str, Any]] = []

    needed_rows = payload.last_row_index
    if needed_rows > sheet_row_count:
        requests.append(_append_rows_request(sheet_id, needed_rows - sheet_row_count))

    if payload.rows:
        requests.append(
            {
                "updateCells": {
                    "range": grid_range(
                        sheet_id,
                        start_row=constants.HEADER_ROW_COUNT,
                        end_row=payload.last_row_index,
                        start_column=0,
                        end_column=layout.column_count,
                    ),
                    "rows": [{"values": row} for row in payload.rows],
                    "fields": "userEnteredValue,userEnteredFormat.numberFormat",
                }
            }
        )

    tail = _tail_request(sheet_id, layout, payload, sheet_row_count=sheet_row_count)
    if tail is not None:
        requests.append(tail)

    requests.extend(payload.extra_requests)
    return requests


def _tail_request(
    sheet_id: int,
    layout: SheetLayout,
    payload: SheetPayload,
    *,
    sheet_row_count: int,
) -> dict[str, Any] | None:
    """Затирает строки ниже данных.

    Без этого удаление операции оставляло бы последнюю строку на месте: новых
    данных на неё не пришло, а старые никто не стёр. Затирается всё до конца
    сетки, а не «сколько было в прошлый раз»: прошлого сервис не помнит, своей
    базы у него нет, и единственная надёжная граница — размер листа.
    """
    start_row = payload.last_row_index
    end_row = max(sheet_row_count, start_row)
    if start_row >= end_row:
        return None
    return {
        "updateCells": {
            "range": grid_range(
                sheet_id,
                start_row=start_row,
                end_row=end_row,
                start_column=0,
                end_column=layout.column_count,
            ),
            "fields": "userEnteredValue",
        }
    }


def _append_rows_request(sheet_id: int, missing: int) -> dict[str, Any]:
    """Наращивает сетку, когда данные перестали помещаться.

    Растём с запасом: расширение стоит места в том же `batchUpdate`, а прирост
    по одной строке на операцию означал бы запрос почти на каждую перерисовку.
    """
    chunks = -(-missing // constants.GRID_ROW_CHUNK)  # округление вверх
    return {
        "appendDimension": {
            "sheetId": sheet_id,
            "dimension": "ROWS",
            "length": chunks * constants.GRID_ROW_CHUNK,
        }
    }


def _header_row_request(sheet_id: int, layout: SheetLayout) -> dict[str, Any]:
    """Пишет и оформляет строку заголовков."""
    cells: list[dict[str, Any]] = []
    for column in layout.columns:
        cell = values.text_cell(column.header)
        cell["userEnteredFormat"] = {
            "backgroundColor": HEADER_BACKGROUND,
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "textFormat": {"bold": True, "fontSize": HEADER_FONT_SIZE},
            "textRotation": {"angle": DATE_HEADER_ROTATION if column.rotated_header else 0},
        }
        cells.append(cell)
    return {
        "updateCells": {
            "range": grid_range(
                sheet_id,
                start_row=0,
                end_row=constants.HEADER_ROW_COUNT,
                start_column=0,
                end_column=layout.column_count,
            ),
            "rows": [{"values": cells}],
            "fields": "userEnteredValue,userEnteredFormat",
        }
    }


def _body_alignment_request(sheet_id: int, layout: SheetLayout) -> dict[str, Any]:
    """Центрирует содержимое всех строк ниже шапки."""
    return {
        "repeatCell": {
            "range": grid_range(
                sheet_id,
                start_row=constants.HEADER_ROW_COUNT,
                start_column=0,
                end_column=layout.column_count,
            ),
            "cell": {
                "userEnteredFormat": {
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                }
            },
            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)",
        }
    }


def _column_width_requests(sheet_id: int, layout: SheetLayout) -> list[dict[str, Any]]:
    """Задаёт ширины колонок.

    Соседние колонки одинаковой ширины склеиваются в один запрос: у листа
    статистики их три десятка по 45 пикселей, и по запросу на каждую тело
    выросло бы вчетверо на пустом месте.
    """
    requests: list[dict[str, Any]] = []
    start = 0
    while start < layout.column_count:
        width = layout.columns[start].width
        end = start + 1
        while end < layout.column_count and layout.columns[end].width == width:
            end += 1
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": start,
                        "endIndex": end,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )
        start = end
    return requests


def _protection_requests(sheet_id: int, layout: SheetLayout) -> list[dict[str, Any]]:
    """Закрывает от правки то, что заполняет система.

    `editors.users` пуст намеренно: документом владеет сервисный аккаунт, и
    пустой список означает «править может только владелец». Пользователь при
    этом остаётся редактором документа и свободно работает в остальных ячейках.

    Даже сплошная защита адресуется прямоугольником по `column_count`, а не
    листом целиком (`{"sheetId": ...}`): лист целиком закрыл бы и свободные
    колонки, ради которых запас и появился.
    """
    editors: dict[str, list[str]] = {"users": []}
    if layout.protect_whole_sheet:
        return [
            {
                "addProtectedRange": {
                    "protectedRange": {
                        "range": grid_range(
                            sheet_id,
                            start_row=0,
                            start_column=0,
                            end_column=layout.column_count,
                        ),
                        "description": "Лист заполняется автоматически",
                        "warningOnly": False,
                        "editors": editors,
                    }
                }
            }
        ]

    requests: list[dict[str, Any]] = [
        {
            "addProtectedRange": {
                "protectedRange": {
                    "range": grid_range(
                        sheet_id,
                        start_row=0,
                        end_row=constants.HEADER_ROW_COUNT,
                        start_column=0,
                        end_column=layout.column_count,
                    ),
                    "description": "Заголовки",
                    "warningOnly": False,
                    "editors": editors,
                }
            }
        }
    ]
    for index in layout.protected_column_indexes():
        requests.append(
            {
                "addProtectedRange": {
                    "protectedRange": {
                        "range": grid_range(
                            sheet_id,
                            start_row=0,
                            start_column=index,
                            end_column=index + 1,
                        ),
                        "description": f"Колонка «{layout.columns[index].header}»",
                        "warningOnly": False,
                        "editors": editors,
                    }
                }
            }
        )
    return requests
