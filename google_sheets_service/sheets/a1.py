"""Адресация ячеек Google Sheets."""

from __future__ import annotations


def column_letter(index_1based: int) -> str:
    """Переводит номер колонки в буквенное обозначение: 1 → A, 27 → AA."""
    if index_1based < 1:
        raise ValueError(f"номер колонки должен быть ≥ 1, получено {index_1based}")
    letters = ""
    remaining = index_1based
    while remaining > 0:
        remaining, remainder = divmod(remaining - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def quote_title(title: str) -> str:
    """Экранирует заголовок листа для A1-ссылки.

    Кавычки нужны заголовкам с пробелами, точками, цифрой в начале и вообще
    любым не-ASCII. Лист статистики называется `Stat. 2026-08-01` — в нём есть и
    пробел, и точки, и дефисы. Старая версия подставляла заголовок в диапазон
    без кавычек и работала лишь потому, что Google оказался снисходителен;
    полагаться на это незачем.
    """
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def qualify(title: str, range_a1: str) -> str:
    """Собирает ссылку вида `'Stat. 2026-08-01'!A2:C10`."""
    return f"{quote_title(title)}!{range_a1}"


def grid_range(
    sheet_id: int,
    *,
    start_row: int = 0,
    end_row: int | None = None,
    start_column: int = 0,
    end_column: int | None = None,
) -> dict[str, int]:
    """Собирает `GridRange` — прямоугольник в терминах Sheets API.

    Индексы нулевые, границы полуинтервальные: `endRowIndex` указывает за
    последнюю строку. Пропущенная граница означает «до конца листа», поэтому
    `None` в словарь не кладётся вовсе.
    """
    result: dict[str, int] = {
        "sheetId": sheet_id,
        "startRowIndex": start_row,
        "startColumnIndex": start_column,
    }
    if end_row is not None:
        result["endRowIndex"] = end_row
    if end_column is not None:
        result["endColumnIndex"] = end_column
    return result
