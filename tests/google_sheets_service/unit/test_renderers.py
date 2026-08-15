"""Построение содержимого листов."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from google_sheets_service import constants
from google_sheets_service.sheets.layout import (
    EXPENSE_BACKGROUND,
    INCOME_BACKGROUND,
    NEUTRAL_BACKGROUND,
)
from google_sheets_service.sync import renderers
from tests.google_sheets_service.factories import (
    PERIOD_END,
    PERIOD_START,
    make_balance,
    make_category,
    make_record,
    make_source,
    make_total,
    make_transfer,
)


def _text(cell: dict[str, Any]) -> str:
    """Текст ячейки."""
    return str(cell["userEnteredValue"].get("stringValue", ""))


def _number(cell: dict[str, Any]) -> float:
    """Число ячейки."""
    return float(cell["userEnteredValue"]["numberValue"])


def test_categories_are_ordered_income_first_then_by_id() -> None:
    """Доходы идут перед расходами, внутри — по идентификатору.

    Порядок устойчив между перерисовками, поэтому строка не прыгает под
    курсором, пока пользователь её правит.
    """
    payload = renderers.render_categories(
        [
            make_category(category_id=3, kind="EXPENSE", title="Еда"),
            make_category(category_id=1, kind="INCOME", title="Зарплата"),
            make_category(category_id=2, kind="EXPENSE", title="Транспорт"),
        ]
    )
    assert [_text(row[4]) for row in payload.rows] == ["Зарплата", "Транспорт", "Еда"]


def test_category_flags_match_kind_and_status() -> None:
    """Колонки Active, Income и Cost — взаимно согласованные флаги."""
    payload = renderers.render_categories(
        [make_category(category_id=1, kind="INCOME", status="INACTIVE", title="Премия")]
    )
    row = payload.rows[0]
    assert (_text(row[1]), _text(row[2]), _text(row[3])) == ("0", "1", "0")


def test_category_associations_and_types_use_their_own_separators() -> None:
    """Псевдонимы разделяются пробелом, типы товаров — запятой.

    Разные разделители унаследованы: псевдоним — всегда одно слово, а тип
    товара может состоять из нескольких.
    """
    payload = renderers.render_categories(
        [
            make_category(
                associations=["еда", "продукты"],
                product_types=["молочные продукты", "выпечка"],
            )
        ]
    )
    row = payload.rows[0]
    assert _text(row[5]) == "еда продукты"
    assert _text(row[6]) == "молочные продукты, выпечка"


def test_bills_take_current_balance_from_computed_balances() -> None:
    """Текущий баланс берётся из расчёта, а не из счёта: он не хранится."""
    payload = renderers.render_bills(
        [make_source(source_id=1, start_balance="1000.00")],
        [make_balance(source_id=1, start_balance="1000.00", balance="850.50")],
    )
    row = payload.rows[0]
    assert _number(row[4]) == 1000.0
    assert _number(row[5]) == 850.5


def test_bills_fall_back_to_start_balance_for_new_source() -> None:
    """У счёта без расчёта в колонку идёт начальный остаток.

    Так выглядит только что созданный счёт: операций по нему ещё нет.
    """
    payload = renderers.render_bills([make_source(start_balance="700.00")], [])
    assert _number(payload.rows[0][5]) == 700.0


def test_operations_mix_records_and_transfers_by_date() -> None:
    """Операции и переводы идут одним списком по дате.

    В реестре они равноправны: развести их по разным местам значило бы спрятать
    от пользователя половину движения денег.
    """
    payload = renderers.render_operations(
        [
            make_record(record_id=5, added_at=date(2026, 8, 3), product_name="Хлеб"),
            make_record(record_id=6, added_at=date(2026, 8, 1), product_name="Молоко"),
        ],
        [make_transfer(transfer_id=1, added_at=date(2026, 8, 2))],
        [make_category(category_id=1, title="Еда")],
        [make_source(source_id=1, title="Карта"), make_source(source_id=2, title="Кошелёк")],
    )
    assert [_text(row[3]) for row in payload.rows] == ["Молоко", "", "Хлеб"]


def test_transfer_row_names_both_sources_and_keeps_amount_positive() -> None:
    """Перевод печатается одной строкой с обоими счетами и без знака.

    Деньги не появились и не исчезли, а переехали: знак означал бы неправду в
    любую сторону.
    """
    payload = renderers.render_operations(
        [],
        [make_transfer(from_source_id=1, to_source_id=2, amount="500.00")],
        [],
        [make_source(source_id=1, title="Карта"), make_source(source_id=2, title="Кошелёк")],
    )
    row = payload.rows[0]
    assert _text(row[4]) == constants.TRANSFER_CATEGORY_TITLE
    assert _text(row[7]) == "Карта → Кошелёк"
    assert _number(row[2]) == 500.0


def test_operation_of_deleted_category_keeps_its_title() -> None:
    """Название удалённой категории остаётся в реестре.

    Удаление мягкое, а операция остаётся навсегда: без названия в колонке была
    бы пустота у траты, которая точно была.
    """
    payload = renderers.render_operations(
        [make_record(category_id=9)],
        [],
        [make_category(category_id=9, status="INACTIVE", title="Старая")],
        [make_source(source_id=1)],
    )
    assert _text(payload.rows[0][4]) == "Старая"


def test_operation_marks_check_origin() -> None:
    """Операция из чека получает отметку в последней колонке."""
    payload = renderers.render_operations(
        [make_record(from_check=True)], [], [make_category()], [make_source()]
    )
    assert _text(payload.rows[0][8]) == constants.CHECK_MARK


def test_statistics_lays_out_blocks_with_separator() -> None:
    """Раскладка: итог доходов, доходы, пустая строка, итог расходов, расходы."""
    payload = renderers.render_statistics(
        [
            make_category(category_id=1, kind="INCOME", title="Зарплата"),
            make_category(category_id=2, kind="EXPENSE", title="Еда"),
        ],
        [],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    titles = [_text(row[0]) for row in payload.rows]
    assert titles == [
        constants.TOTAL_INCOME_TITLE,
        "Зарплата",
        "",
        constants.TOTAL_EXPENSE_TITLE,
        "Еда",
    ]


def test_statistics_separator_row_is_filled_with_empty_cells() -> None:
    """Разделитель заполнен пустыми ячейками, а не оставлен коротким.

    Строка без ячеек означает «не трогать», и на её месте осталась бы категория
    из прошлой перерисовки.
    """
    payload = renderers.render_statistics(
        [make_category(kind="INCOME")],
        [],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    separator = payload.rows[2]
    assert len(separator) == 2 + 31
    assert all(cell == {"userEnteredValue": {}} for cell in separator)


def test_statistics_has_column_per_day_of_period() -> None:
    """Колонок ровно столько, сколько дней в периоде.

    Границы полуинтервальные: первое сентября принадлежит следующему месяцу.
    """
    payload = renderers.render_statistics(
        [make_category(kind="INCOME")],
        [],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    assert len(payload.rows[0]) == 2 + 31


def test_statistics_sums_days_into_total_and_block_total() -> None:
    """Итог категории — сумма её дней, итог блока — сумма его категорий."""
    payload = renderers.render_statistics(
        [
            make_category(category_id=1, kind="EXPENSE", title="Еда"),
            make_category(category_id=2, kind="EXPENSE", title="Транспорт"),
        ],
        [
            make_total(category_id=1, day=date(2026, 8, 1), total="-100.50"),
            make_total(category_id=1, day=date(2026, 8, 2), total="-49.50"),
            make_total(category_id=2, day=date(2026, 8, 1), total="-30.00"),
        ],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    expense_total, food, transport = payload.rows[2], payload.rows[3], payload.rows[4]
    assert _number(food[1]) == -150.0
    assert _number(transport[1]) == -30.0
    assert _number(expense_total[1]) == -180.0
    # Первый день: обе категории вместе.
    assert _number(expense_total[2]) == -130.5


def test_statistics_keeps_kopecks() -> None:
    """Копейки доживают до листа.

    Старая версия сворачивала сумму через `int()` и систематически занижала
    расходы: `int(-1234.56)` даёт `-1234`.
    """
    payload = renderers.render_statistics(
        [make_category(category_id=1, kind="EXPENSE")],
        [make_total(category_id=1, day=date(2026, 8, 1), total="-1234.56")],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    # Доходных категорий нет, поэтому строки такие: итог доходов, разделитель,
    # итог расходов, сама категория.
    assert _number(payload.rows[3][1]) == -1234.56


def test_statistics_totals_are_computed_in_decimal() -> None:
    """Итоги считаются в Decimal, а не во float.

    Три раза по 0.1 во float дают 0.30000000000000004; в Decimal — ровно 0.3.
    """
    payload = renderers.render_statistics(
        [make_category(category_id=1, kind="EXPENSE")],
        [
            make_total(category_id=1, day=date(2026, 8, day), total="0.10")
            for day in (1, 2, 3)
        ],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    assert Decimal(str(_number(payload.rows[3][1]))) == Decimal("0.3")


def test_statistics_repaints_blocks_after_resetting_fill() -> None:
    """Заливка сначала сбрасывается, потом кладутся блоки.

    Число категорий меняется, и укоротившийся блок иначе оставил бы за собой
    крашеный хвост от прошлой перерисовки.
    """
    payload = renderers.render_statistics(
        [
            make_category(category_id=1, kind="INCOME"),
            make_category(category_id=2, kind="EXPENSE"),
        ],
        [],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    fills = [
        request["repeatCell"]["cell"]["userEnteredFormat"]["backgroundColor"]
        for request in payload.extra_requests
    ]
    assert fills == [NEUTRAL_BACKGROUND, INCOME_BACKGROUND, EXPENSE_BACKGROUND]

    reset = payload.extra_requests[0]["repeatCell"]["range"]
    assert reset["sheetId"] == 7
    # У сброса нет нижней границы: он идёт до конца листа.
    assert "endRowIndex" not in reset


def test_statistics_blocks_cover_their_rows() -> None:
    """Границы цветных блоков совпадают со строками, которые они описывают."""
    payload = renderers.render_statistics(
        [
            make_category(category_id=1, kind="INCOME"),
            make_category(category_id=2, kind="INCOME"),
            make_category(category_id=3, kind="EXPENSE"),
        ],
        [],
        start_date=PERIOD_START,
        end_date=PERIOD_END,
        sheet_id=7,
    )
    income = payload.extra_requests[1]["repeatCell"]["range"]
    expense = payload.extra_requests[2]["repeatCell"]["range"]
    # Итог доходов и две категории — строки 2..4 листа.
    assert (income["startRowIndex"], income["endRowIndex"]) == (1, 4)
    # После пустого разделителя: итог расходов и одна категория.
    assert (expense["startRowIndex"], expense["endRowIndex"]) == (5, 7)
