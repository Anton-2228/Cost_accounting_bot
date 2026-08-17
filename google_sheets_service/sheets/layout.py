"""Декларативное описание листа: колонки, оформление, защиты.

Старая версия держала это четырьмя простынями сырых тел запросов на 445 строк,
с зашитыми номерами листов 0 и 1. Здесь лист описывается данными, а тела
запросов собираются из описания в :mod:`google_sheets_service.sheets.requests`.
Вид документа при этом сохранён один в один.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google_sheets_service import constants

#: Фон строки заголовков.
HEADER_BACKGROUND = {"red": 0.9, "green": 0.9, "blue": 0.9}
#: Фон блока доходов на листе статистики.
INCOME_BACKGROUND = {"red": 0.824, "green": 0.96, "blue": 0.753}
#: Фон блока расходов там же.
EXPENSE_BACKGROUND = {"red": 0.921, "green": 0.703, "blue": 0.703}
#: Белый: им сбрасывается заливка перед тем, как положить блоки заново. Без
#: сброса блок, ставший короче, оставил бы за собой крашеный хвост.
NEUTRAL_BACKGROUND = {"red": 1.0, "green": 1.0, "blue": 1.0}

HEADER_FONT_SIZE = 10
#: Поворот заголовков-дат на листе статистики: иначе колонка в 45 пикселей не
#: вмещает дату и таблица становится нечитаемой.
DATE_HEADER_ROTATION = -90


@dataclass(frozen=True)
class Column:
    """Одна колонка листа."""

    header: str
    width: int
    #: Колонку заполняет система, и правка пользователя ей только повредит:
    #: идентификатор связывает строку с записью в базе, баланс вычисляется.
    protected: bool = False
    #: Заголовок пишется повёрнутым.
    rotated_header: bool = False


@dataclass(frozen=True)
class SheetLayout:
    """Полное описание листа: из чего он состоит и как выглядит."""

    columns: tuple[Column, ...]
    #: Защитить все системные колонки, а не отдельные. Так закрыты реестр
    #: операций и статистика: они производны от базы, и правка в них была бы
    #: потеряна следующей же перерисовкой — молча и без объяснений. Свободных
    #: колонок справа защита не касается ни при каком значении флага.
    protect_whole_sheet: bool = False

    @property
    def column_count(self) -> int:
        """Число колонок, которые заполняет система."""
        return len(self.columns)

    @property
    def grid_column_count(self) -> int:
        """Ширина сетки: системные колонки плюс запас под формулы пользователя.

        Разделение с :attr:`column_count` принципиально. Всё, что пишет,
        оформляет, затирает и защищает, опирается на `column_count` — иначе
        перерисовка добралась бы до колонок, которые ей не принадлежат, и
        стирала бы формулы при каждом проходе.
        """
        return len(self.columns) + constants.SPARE_COLUMN_COUNT

    @property
    def headers(self) -> tuple[str, ...]:
        """Заголовки колонок."""
        return tuple(column.header for column in self.columns)

    @property
    def widths(self) -> tuple[int, ...]:
        """Ширины колонок в пикселях."""
        return tuple(column.width for column in self.columns)

    def protected_column_indexes(self) -> tuple[int, ...]:
        """Нулевые индексы колонок, закрытых от правки."""
        return tuple(index for index, column in enumerate(self.columns) if column.protected)


@dataclass(frozen=True)
class SheetPayload:
    """Содержимое листа, готовое к отправке.

    `rows` — только строки данных, без заголовка: шапка ставится один раз при
    создании листа и перерисовкой не трогается.

    `extra_requests` — оформление, зависящее от самих данных. Такое есть ровно
    на одном листе: блоки доходов и расходов в статистике меняют высоту вместе
    с числом активных категорий, поэтому их приходится перекрашивать при каждой
    перерисовке, а не однажды при создании.
    """

    rows: list[list[dict[str, Any]]] = field(default_factory=list)
    extra_requests: list[dict[str, Any]] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        """Число строк данных."""
        return len(self.rows)

    @property
    def last_row_index(self) -> int:
        """Индекс строки за последней строкой данных (0-based, полуинтервал)."""
        return constants.HEADER_ROW_COUNT + self.row_count
