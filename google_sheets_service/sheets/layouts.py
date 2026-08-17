"""Описания четырёх листов документа.

Состав колонок и ширины унаследованы от старой версии дословно: пользователь
открывает ту же таблицу, что и раньше. Изменились только защиты — они стали
описываться флагом колонки, а не отдельной простынёй запросов.
"""

from __future__ import annotations

from datetime import date, timedelta

from google_sheets_service import constants
from google_sheets_service.sheets.layout import Column, SheetLayout

#: Лист справочника категорий. Единственный способ править категории: бот их не
#: создаёт, поэтому колонки B–G пользователь заполняет руками.
CATEGORIES_LAYOUT = SheetLayout(
    columns=(
        Column(header="ID", width=50, protected=True),
        Column(header="Active", width=100),
        Column(header="Income", width=100),
        Column(header="Cost", width=100),
        Column(header="Name", width=200),
        Column(header="Associations", width=300),
        Column(header="Product types", width=400),
    )
)

#: Лист счетов. `Current balance` защищён: он вычисляется из операций и
#: переводов, и правка в нём была бы стёрта следующей же перерисовкой.
BILLS_LAYOUT = SheetLayout(
    columns=(
        Column(header="ID", width=50, protected=True),
        Column(header="Active", width=100),
        Column(header="Name", width=200),
        Column(header="Associations", width=300),
        Column(header="Start balance", width=120),
        Column(header="Current balance", width=120, protected=True),
    )
)

#: Реестр операций периода. Защищён целиком: производен от базы.
OPERATIONS_LAYOUT = SheetLayout(
    columns=(
        Column(header="ID", width=50),
        Column(header="Date", width=130),
        Column(header="Amount", width=100),
        Column(header="Name", width=400),
        Column(header="Category", width=200),
        Column(header="Type", width=150),
        Column(header="Notes", width=200),
        Column(header="Source", width=150),
        Column(header="Check", width=50),
    ),
    protect_whole_sheet=True,
)

#: Архив разобранных чеков месяца. Две колонки: номер чека и его расшифровка
#: целиком. Таблица служит в том числе архивом, а отметка «чек был» архивом не
#: является — в реестре у позиций стоит номер, здесь по нему лежит сам чек.
#: Защищён целиком: производен от базы, как и реестр.
CHECKS_LAYOUT = SheetLayout(
    columns=(
        Column(header="ID", width=50),
        Column(header="Check", width=600),
    ),
    protect_whole_sheet=True,
)

#: Ширина колонки одного дня на листе статистики.
DAY_COLUMN_WIDTH = 45


def statistics_layout(start_date: date, end_date: date) -> SheetLayout:
    """Собирает описание листа статистики под конкретный период.

    Колонок здесь столько, сколько дней в периоде, поэтому описание строится, а
    не лежит константой. Границы полуинтервальные: день `end_date` принадлежит
    уже следующему месяцу и колонки не получает.
    """
    columns = [
        Column(header="Category", width=200),
        Column(header="Total", width=100),
    ]
    columns.extend(
        Column(header=day.isoformat(), width=DAY_COLUMN_WIDTH, rotated_header=True)
        for day in period_days(start_date, end_date)
    )
    return SheetLayout(columns=tuple(columns), protect_whole_sheet=True)


def period_days(start_date: date, end_date: date) -> list[date]:
    """Дни периода: от начала включительно до конца исключительно.

    Старая версия считала длину месяца по таблице в JSON, где февраль был жёстко
    прописан двадцатью восемью днями. В високосный год последний день пропадал
    из статистики вместе с операциями, которые в него попали.
    """
    if end_date <= start_date:
        return []
    return [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days)]


def operations_sheet_title(start_date: date) -> str:
    """Заголовок листа операций — дата начала периода."""
    return start_date.isoformat()


def statistics_sheet_title(start_date: date) -> str:
    """Заголовок листа статистики — та же дата с префиксом."""
    return f"{constants.STATISTICS_TITLE_PREFIX}{start_date.isoformat()}"


def checks_sheet_title(start_date: date) -> str:
    """Заголовок листа чеков — та же дата со своим префиксом."""
    return f"{constants.CHECKS_TITLE_PREFIX}{start_date.isoformat()}"
