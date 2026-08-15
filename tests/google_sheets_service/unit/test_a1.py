"""Адресация ячеек и экранирование заголовков листов."""

from __future__ import annotations

import pytest

from google_sheets_service.sheets.a1 import column_letter, grid_range, qualify, quote_title


@pytest.mark.parametrize(
    ("index", "expected"),
    [(1, "A"), (2, "B"), (9, "I"), (26, "Z"), (27, "AA"), (33, "AG"), (52, "AZ")],
)
def test_column_letter(index: int, expected: str) -> None:
    """Номер колонки переводится в буквы."""
    assert column_letter(index) == expected


def test_column_letter_rejects_zero() -> None:
    """Нулевой колонки не бывает: нумерация в A1 начинается с единицы."""
    with pytest.raises(ValueError, match="номер колонки"):
        column_letter(0)


def test_qualify_quotes_statistics_title() -> None:
    """Заголовок листа статистики экранируется.

    В нём есть и пробел, и точка, и дефисы. Старая версия подставляла его в
    диапазон без кавычек и работала лишь по снисходительности Google.
    """
    assert qualify("Stat. 2026-08-01", "A2:C10") == "'Stat. 2026-08-01'!A2:C10"


def test_quote_title_escapes_apostrophe() -> None:
    """Апостроф в заголовке удваивается, иначе кавычка закроется раньше времени."""
    assert quote_title("Ба'ланс") == "'Ба''ланс'"


def test_grid_range_omits_open_boundaries() -> None:
    """Пропущенная граница означает «до конца листа» и в тело не попадает."""
    assert grid_range(5, start_row=1, start_column=0) == {
        "sheetId": 5,
        "startRowIndex": 1,
        "startColumnIndex": 0,
    }


def test_grid_range_is_half_open() -> None:
    """Границы полуинтервальные: `endRowIndex` указывает за последнюю строку."""
    assert grid_range(5, start_row=1, end_row=3, start_column=0, end_column=2) == {
        "sheetId": 5,
        "startRowIndex": 1,
        "endRowIndex": 3,
        "startColumnIndex": 0,
        "endColumnIndex": 2,
    }
