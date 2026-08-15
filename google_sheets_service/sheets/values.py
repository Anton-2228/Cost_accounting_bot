"""Значения ячеек: доменные величины в тело запроса и обратно.

Два направления, и оба нетривиальны ровно в одном месте — числах.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

#: Формат денежной колонки: два знака после запятой, разделитель разрядов.
#: Отображение локальное — в русской таблице пользователь увидит запятую.
MONEY_PATTERN = "#,##0.00"


def text_cell(value: str) -> dict[str, Any]:
    """Текстовая ячейка."""
    return {"userEnteredValue": {"stringValue": value}}


def int_cell(value: int) -> dict[str, Any]:
    """Целочисленная ячейка без денежного формата.

    Отдельно от :func:`number_cell` ради колонки `ID`: с форматом в два знака
    идентификатор отображался бы как «1,00», и пользователь, переносящий строку
    руками, скопировал бы вместе с ним запятую.
    """
    return {
        "userEnteredValue": {"numberValue": value},
        "userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0"}},
    }


def number_cell(value: Decimal) -> dict[str, Any]:
    """Денежная ячейка: число с форматом в два знака.

    В протоколе Google число — это `double`, и `Decimal` приходится приводить к
    `float`. Потери здесь нет: `NUMERIC(14, 2)` укладывается в 14 значащих цифр,
    а `double` точен до пятнадцати. Важно другое — приведение делается **только
    на границе с Google**. Внутри сервиса деньги остаются `Decimal`, поэтому
    сложение, разбиение по дням и итоги считаются без накопления погрешности.
    """
    return {
        "userEnteredValue": {"numberValue": float(value)},
        "userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": MONEY_PATTERN}},
    }


def date_cell(value: date) -> dict[str, Any]:
    """Ячейка с датой в виде текста `2026-08-14`.

    Именно текстом, а не датой Google: заголовки листов и колонки статистики
    строятся из тех же ISO-строк, и единый вид избавляет от разночтений между
    локалью документа и тем, что видит сервис.
    """
    return text_cell(value.isoformat())


def empty_cell() -> dict[str, Any]:
    """Пустая ячейка.

    Пустой `userEnteredValue` — именно то, чем затирается хвост листа: он
    стирает и значение, и всё, что пользователь мог там набрать.
    """
    return {"userEnteredValue": {}}


def to_cell_text(value: Any) -> str:
    """Приводит прочитанную из листа ячейку к строке для api.

    Api принимает лист прямоугольником строк, а `UNFORMATTED_VALUE` возвращает
    типизированные значения. Наивный `str` здесь ломает импорт: флаг `Active`
    приезжает числом `1`, `str(1.0)` даёт `"1.0"`, а `api/validation.py` сверяет
    колонку со списком `("0", "1")` — и лист отвергается целиком, с русской
    ошибкой на каждой строке.

    Порядок проверок важен: `bool` в Python — подкласс `int`, и без отдельной
    ветки логическое значение превратилось бы в `"1"` вместо `"TRUE"`.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Целое, записанное числом с плавающей точкой, — обычный случай: Google
        # возвращает `1` для флага и `1500` для круглой суммы.
        if value.is_integer():
            return str(int(value))
        # `repr`, а не `str(Decimal(value))`: первый даёт кратчайшую запись,
        # которая читается обратно в то же самое число, второй — семнадцать
        # знаков двоичного хвоста.
        return repr(value)
    return str(value)


def to_cell_rows(values: list[list[Any]], *, width: int) -> list[list[str]]:
    """Приводит прочитанный прямоугольник к строкам одинаковой ширины.

    Google обрезает хвостовые пустые ячейки, поэтому строка с незаполненной
    последней колонкой приходит короче остальных. Api выравнивает их и сам, но
    делать это здесь дешевле: иначе по сети едет рваная матрица, в которой
    невозможно глазами найти сдвиг колонки.
    """
    rows: list[list[str]] = []
    for row in values:
        cells = [to_cell_text(cell) for cell in row[:width]]
        cells.extend([""] * (width - len(cells)))
        rows.append(cells)
    return rows
