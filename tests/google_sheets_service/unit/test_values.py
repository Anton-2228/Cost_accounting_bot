"""Значения ячеек: запись в лист и обратное чтение."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from google_sheets_service.sheets import values


def test_number_cell_keeps_two_decimal_places() -> None:
    """Денежная ячейка получает формат в два знака."""
    cell = values.number_cell(Decimal("149.50"))
    assert cell["userEnteredValue"]["numberValue"] == pytest.approx(149.5)
    assert cell["userEnteredFormat"]["numberFormat"]["pattern"] == values.MONEY_PATTERN


def test_int_cell_has_no_money_format() -> None:
    """Идентификатор пишется целым: «1,00» в колонке ID сбивал бы с толку."""
    assert values.int_cell(42)["userEnteredFormat"]["numberFormat"]["pattern"] == "0"


def test_empty_cell_clears_value() -> None:
    """Пустая ячейка стирает содержимое, а не просто ничего не пишет."""
    assert values.empty_cell() == {"userEnteredValue": {}}


def test_date_cell_is_iso_text() -> None:
    """Дата печатается тем же ISO-видом, что и в заголовках листов."""
    assert values.date_cell(date(2026, 8, 14))["userEnteredValue"]["stringValue"] == "2026-08-14"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        ("Еда", "Еда"),
        (1, "1"),
        (0, "0"),
        # Главный случай: Google возвращает флаг числом, и наивный `str` дал бы
        # «1.0» — валидация api сверяет колонку со списком ("0", "1") и
        # отвергла бы весь лист.
        (1.0, "1"),
        (0.0, "0"),
        (1500.0, "1500"),
        (1000.5, "1000.5"),
        (149.99, "149.99"),
        # Логическое значение проверяется раньше числа: bool — подкласс int, и
        # без отдельной ветки True превратился бы в «1».
        (True, "TRUE"),
        (False, "FALSE"),
    ],
)
def test_to_cell_text_normalizes_every_kind_of_cell(raw: object, expected: str) -> None:
    """Прочитанная ячейка приводится к строке без искажения значения."""
    assert values.to_cell_text(raw) == expected


def test_to_cell_rows_pads_short_rows() -> None:
    """Строки выравниваются по ширине листа.

    Google обрезает хвостовые пустые ячейки, поэтому строка с незаполненной
    последней колонкой приходит короче остальных.
    """
    rows = values.to_cell_rows([["1", "Еда"], ["2"]], width=4)
    assert rows == [["1", "Еда", "", ""], ["2", "", "", ""]]


def test_to_cell_rows_trims_extra_cells() -> None:
    """Лишние колонки отбрасываются: api ждёт прямоугольник известной ширины."""
    assert values.to_cell_rows([["1", "2", "3"]], width=2) == [["1", "2"]]
