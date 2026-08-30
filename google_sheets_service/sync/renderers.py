"""Построение содержимого листов из данных api.

Чистые функции: доменные структуры на входе, ячейки на выходе. Ни одного
обращения к сети — читает движок, поэтому одна выборка обслуживает целый лист.
Старая версия делала запрос на категорию ради статистики и два запроса на
операцию ради реестра; здесь всё группируется в памяти.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from google_sheets_service import constants
from google_sheets_service.main_api.dto import (
    Category,
    CategoryDailyTotal,
    Check,
    Record,
    Source,
    SourceBalance,
    Transfer,
)
from google_sheets_service.sheets import values
from google_sheets_service.sheets.a1 import grid_range
from google_sheets_service.sheets.layout import (
    EXPENSE_BACKGROUND,
    INCOME_BACKGROUND,
    NEUTRAL_BACKGROUND,
    SheetPayload,
)
from google_sheets_service.sheets.layouts import period_days

#: Значение колонок `Active`, `Income`, `Cost`: лист хранит их как флаги.
_FLAG_ON = "1"
_FLAG_OFF = "0"


def render_categories(categories: list[Category]) -> SheetPayload:
    """Строит лист `Categories`.

    Порядок — доходы, затем расходы, внутри по идентификатору: он устойчив
    между перерисовками, и строка не прыгает под курсором, пока пользователь её
    правит.
    """
    ordered = sorted(categories, key=lambda item: (not item.is_income, item.id))
    rows = [
        [
            values.int_cell(category.id),
            values.text_cell(_flag(category.status == "ACTIVE")),
            values.text_cell(_flag(category.is_income)),
            values.text_cell(_flag(not category.is_income)),
            values.text_cell(category.title),
            values.text_cell(" ".join(category.associations)),
            values.text_cell(", ".join(category.product_types)),
        ]
        for category in ordered
    ]
    return SheetPayload(rows=rows)


def render_bills(sources: list[Source], balances: list[SourceBalance]) -> SheetPayload:
    """Строит лист `Bills`.

    `Current balance` берётся из посчитанных балансов, а не из счёта: баланс не
    хранится. Счёт без баланса — не сбой, а обычное дело для только что
    созданного: в ответе `balances` его ещё нет, и в колонку идёт начальный
    остаток.
    """
    balance_by_source = {balance.source_id: balance.balance for balance in balances}
    rows = [
        [
            values.int_cell(source.id),
            values.text_cell(_flag(source.status == "ACTIVE")),
            values.text_cell(source.title),
            values.text_cell(" ".join(source.associations)),
            values.text_cell(source.currency),
            values.number_cell(source.start_balance),
            values.number_cell(balance_by_source.get(source.id, source.start_balance)),
        ]
        for source in sorted(sources, key=lambda item: item.id)
    ]
    return SheetPayload(rows=rows)


def render_operations(
    records: list[Record],
    transfers: list[Transfer],
    categories: list[Category],
    sources: list[Source],
) -> SheetPayload:
    """Строит реестр операций периода.

    Операции и переводы идут одним списком, упорядоченным по дате: в реестре они
    равноправны, и разносить их по разным местам значило бы прятать от
    пользователя половину движения денег. Отдельного листа для переводов нет —
    у перевода в колонке `Category` стоит подпись, а в `Source` оба счёта.

    Справочники приходят вместе с удалёнными: операция удалённой категории
    остаётся в реестре навсегда, и без её названия в колонке была бы пустота у
    траты, которая точно была.
    """
    category_titles = {category.id: category.title for category in categories}
    source_titles = {source.id: source.title for source in sources}
    # Валюты счетов нужны переводам: сумма перевода выражена в валюте
    # счёта-источника, и взять её из самого перевода нельзя — там её нет.
    source_currencies = {source.id: source.currency for source in sources}

    entries: list[tuple[date, int, list[dict[str, Any]]]] = []
    for record in records:
        entries.append((record.added_at, record.id, _record_row(record, category_titles,
                                                                source_titles)))
    for transfer in transfers:
        entries.append(
            (
                transfer.added_at,
                transfer.id,
                _transfer_row(transfer, source_titles, source_currencies),
            )
        )

    entries.sort(key=lambda entry: (entry[0], entry[1]))
    return SheetPayload(rows=[row for _, _, row in entries])


def render_checks(checks: list[Check]) -> SheetPayload:
    """Строит лист-архив чеков месяца: номер и расшифровка целиком.

    Порядок по номеру: он устойчив между перерисовками, и строка не прыгает под
    курсором. Позиции чека в реестре ссылаются сюда тем же номером.
    """
    rows = [
        [values.int_cell(check.id), values.text_cell(_check_json(check))]
        for check in sorted(checks, key=lambda item: item.id)
    ]
    return SheetPayload(rows=rows)


def _check_json(check: Check) -> str:
    """Расшифровка чека одной строкой, обрезанная под лимит ячейки.

    Компактный JSON без пробелов и без экранирования кириллицы: ячейка тем
    самым остаётся читаемой глазами, а разбор обратно — возможным.

    Чек длиннее лимита обрезается с пометкой, а не отбрасывается и не роняет
    задачу. Отказ Google на слишком длинном значении — 400, то есть ошибка
    терминальная: одна оптовая закупка останавливала бы лист навсегда. Обрезка
    ломает JSON, и пометка прямо говорит, где лежит целое.
    """
    text = json.dumps(check.raw_payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= constants.CELL_TEXT_LIMIT:
        return text
    suffix = constants.CHECK_TRUNCATED_SUFFIX.format(check_id=check.id)
    return text[: constants.CELL_TEXT_LIMIT - len(suffix)] + suffix


def render_statistics(
    categories: list[Category],
    totals: list[CategoryDailyTotal],
    *,
    start_date: date,
    end_date: date,
    sheet_id: int,
) -> SheetPayload:
    """Строит лист статистики: строка на категорию, колонка на день.

    Раскладка унаследована: строка «Общие доходы» и активные категории дохода,
    одна пустая строка, строка «Общие расходы» и активные категории расхода.
    Пустая строка — не украшение: она отделяет блоки, которые красятся разными
    цветами, и без неё границу невозможно увидеть.

    `sheet_id` нужен запросам заливки: адресовать прямоугольник в Google иначе
    нечем. Это единственный лист, оформление которого зависит от данных.
    """
    days = period_days(start_date, end_date)
    column_count = 2 + len(days)
    by_category: dict[int, dict[date, Decimal]] = defaultdict(dict)
    for item in totals:
        by_category[item.category_id][item.day] = item.total

    income = [category for category in categories if category.is_income]
    expense = [category for category in categories if not category.is_income]

    rows: list[list[dict[str, Any]]] = []
    rows.append(_total_row(constants.TOTAL_INCOME_TITLE, income, by_category, days))
    rows.extend(_category_row(category, by_category, days) for category in income)
    # Разделитель заполняется пустыми ячейками, а не оставляется коротким:
    # строка без ячеек в `updateCells` означает «не трогать», и на её месте
    # осталась бы категория из прошлой перерисовки.
    rows.append([values.empty_cell() for _ in range(column_count)])
    rows.append(_total_row(constants.TOTAL_EXPENSE_TITLE, expense, by_category, days))
    rows.extend(_category_row(category, by_category, days) for category in expense)

    income_block = (0, 1 + len(income))
    expense_block = (income_block[1] + 1, income_block[1] + 2 + len(expense))
    return SheetPayload(
        rows=rows,
        extra_requests=_block_colour_requests(
            sheet_id=sheet_id,
            column_count=column_count,
            income_block=income_block,
            expense_block=expense_block,
        ),
    )


def _record_row(
    record: Record,
    category_titles: dict[int, str],
    source_titles: dict[int, str],
) -> list[dict[str, Any]]:
    """Строка реестра для операции.

    В колонке `Check` стоит номер чека, а не отметка о его существовании: по
    нему пользователь находит строку на листе-архиве, где лежит сам чек.
    """
    return [
        values.int_cell(record.id),
        values.date_cell(record.added_at),
        values.number_cell(record.amount),
        values.text_cell(record.currency),
        values.text_cell(record.product_name or ""),
        values.text_cell(category_titles.get(record.category_id, "")),
        values.text_cell(record.product_type or ""),
        values.text_cell(record.notes),
        values.text_cell(source_titles.get(record.source_id, "")),
        values.text_cell("") if record.check_id is None else values.int_cell(record.check_id),
    ]


def _transfer_row(
    transfer: Transfer,
    source_titles: dict[int, str],
    source_currencies: dict[int, str],
) -> list[dict[str, Any]]:
    """Строка реестра для перевода.

    Сумма печатается положительной: деньги не появились и не исчезли, а
    переехали, и знак у такой строки означал бы неправду в любую сторону.

    В колонке `Currency` — валюта **счёта-источника**: именно в ней названа
    сумма. Если счёт-получатель ведётся в другой валюте, зачисленное считается
    по курсу на день перевода, и на листе операций этой второй суммы нет — она
    видна только в остатке принимающего счёта.
    """
    source = source_titles.get(transfer.from_source_id, "")
    target = source_titles.get(transfer.to_source_id, "")
    return [
        values.int_cell(transfer.id),
        values.date_cell(transfer.added_at),
        values.number_cell(transfer.amount),
        values.text_cell(source_currencies.get(transfer.from_source_id, "")),
        values.text_cell(""),
        values.text_cell(constants.TRANSFER_CATEGORY_TITLE),
        values.text_cell(""),
        values.text_cell(transfer.notes),
        values.text_cell(f"{source}{constants.TRANSFER_SOURCE_SEPARATOR}{target}"),
        values.text_cell(""),
    ]


def _category_row(
    category: Category,
    by_category: dict[int, dict[date, Decimal]],
    days: list[date],
) -> list[dict[str, Any]]:
    """Строка статистики по одной категории."""
    daily = by_category.get(category.id, {})
    total = sum(daily.values(), Decimal(0))
    row = [values.text_cell(category.title), values.number_cell(total)]
    row.extend(values.number_cell(daily.get(day, Decimal(0))) for day in days)
    return row


def _total_row(
    title: str,
    categories: list[Category],
    by_category: dict[int, dict[date, Decimal]],
    days: list[date],
) -> list[dict[str, Any]]:
    """Итоговая строка блока: сумма по всем его категориям за каждый день."""
    per_day = {
        day: sum(
            (by_category.get(category.id, {}).get(day, Decimal(0)) for category in categories),
            Decimal(0),
        )
        for day in days
    }
    row = [values.text_cell(title), values.number_cell(sum(per_day.values(), Decimal(0)))]
    row.extend(values.number_cell(per_day[day]) for day in days)
    return row


def _block_colour_requests(
    *,
    sheet_id: int,
    column_count: int,
    income_block: tuple[int, int],
    expense_block: tuple[int, int],
) -> list[dict[str, Any]]:
    """Красит блоки доходов и расходов.

    Сначала заливка сбрасывается на всём листе, и только потом кладутся блоки:
    число категорий меняется, и укоротившийся блок иначе оставил бы за собой
    крашеный хвост от прошлой перерисовки.
    """
    requests: list[dict[str, Any]] = [
        _fill_request(
            NEUTRAL_BACKGROUND,
            sheet_id=sheet_id,
            start_row=0,
            end_row=None,
            column_count=column_count,
        )
    ]
    for background, (start, end) in (
        (INCOME_BACKGROUND, income_block),
        (EXPENSE_BACKGROUND, expense_block),
    ):
        if end > start:
            requests.append(
                _fill_request(
                    background,
                    sheet_id=sheet_id,
                    start_row=constants.HEADER_ROW_COUNT + start,
                    end_row=constants.HEADER_ROW_COUNT + end,
                    column_count=column_count,
                )
            )
    return requests


def _fill_request(
    background: dict[str, float],
    *,
    sheet_id: int,
    start_row: int,
    end_row: int | None,
    column_count: int,
) -> dict[str, Any]:
    """Заливка прямоугольника одним цветом."""
    return {
        "repeatCell": {
            "range": grid_range(
                sheet_id,
                start_row=max(start_row, constants.HEADER_ROW_COUNT),
                end_row=end_row,
                start_column=0,
                end_column=column_count,
            ),
            "cell": {"userEnteredFormat": {"backgroundColor": background}},
            "fields": "userEnteredFormat.backgroundColor",
        }
    }


def _flag(value: bool) -> str:
    """Логическое значение в том виде, в каком его хранит лист."""
    return _FLAG_ON if value else _FLAG_OFF
