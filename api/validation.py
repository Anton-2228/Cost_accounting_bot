"""Разбор и проверка строк листов `Categories` и `Bills`.

Единственное место в api, где текст ошибки пишется по-русски и предназначен
пользователю. Так сделано намеренно: сообщение собирается из пользовательских
данных и номера строки листа («В категориях в 5 строке Active странный»),
поэтому выразить его кодом ошибки и перевести в боте невозможно — оно едет как
**данные**, в поле ответа.

Формулировки унаследованы дословно. Нумерация строк смещена на единицу
относительно листа (диапазон начинается со второй строки, а счёт идёт с
первой) — пользователи привыкли к этим номерам, поэтому смещение сохранено.

Отличий от старой версии два, оба чинят баги:

* `Balance` принимает дробное значение. Прежний текст требовал целое число, но
  проверка стояла `float(...)`, то есть копейки проходили, а сообщение врало.
  Деньги везде `Decimal`, ограничивать их целыми незачем.
* Проверяется, что ID из строки существует в этом документе. Прежний код брал
  `by_id[int(row[0])]` без проверки, и опечатка в ID или строка, скопированная
  из чужой таблицы, роняли весь импорт с `KeyError`.
* Проверяется, что один ID не встречается в листе дважды. Скопированная строка
  иначе означала бы две несовместимые правки одной записи: какая из них
  победит, зависело бы от порядка строк, а строка «удалить» вместе со строкой
  «обновить» роняла импорт с `KeyError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from api.core.text import normalize_terms

#: Колонки листа `Categories`: ID · Active · Income · Cost · Name · Associations · Product types
CATEGORY_WIDTH = 7
#: Колонки листа `Bills`: ID · Active · Name · Associations · Start balance · Current balance
SOURCE_WIDTH = 6

#: Сколько полей после ID означают «строку очистили» (пустые ⇒ удаление).
#: У источников последняя колонка (`Current balance`) не в счёт: её пишет
#: перерисовка, пользователь её не заполняет.
CATEGORY_MEANINGFUL_FIELDS = 6
SOURCE_MEANINGFUL_FIELDS = 4

_FLAGS = ("0", "1")

#: Разделители разрядов, которые Google подставляет в отформатированное число.
#: Второй — неразрывный пробел (U+00A0), именно он приходит из таблиц с русской
#: локалью, и на глаз от обычного не отличается.
_THOUSAND_SEPARATORS = (" ", " ")


def pad(rows: Sequence[Sequence[str]], width: int) -> list[list[str]]:
    """Дополняет короткие строки пустыми ячейками до ширины листа.

    Google Sheets обрезает хвостовые пустые ячейки, поэтому строка с пустым
    полем `Product types` приходит короче остальных. Без выравнивания любой
    доступ по индексу превращается в `IndexError`.
    """
    return [[*row, *[""] * (width - len(row))][:width] for row in rows]


def is_blank(row: Sequence[str]) -> bool:
    """Пустая строка листа целиком."""
    return all(cell.strip() == "" for cell in row)


def is_cleared(row: Sequence[str], meaningful_fields: int) -> bool:
    """Строку очистили: ID остался, содержимое стёрли — значит, удаление."""
    return row[0].strip() != "" and all(
        cell.strip() == "" for cell in row[1 : meaningful_fields + 1]
    )


def parse_id(cell: str) -> int | None:
    """Читает ID из ячейки. `None` — ячейка пуста (строка новая) или не число."""
    value = cell.strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_aliases(cell: str, title: str) -> list[str]:
    """Псевдонимы строки: то, что записано в ячейке, плюс само название.

    Название всегда попадает в набор — иначе категорию нельзя было бы указать
    её собственным именем.
    """
    return normalize_terms([*cell.split(), title])


def parse_product_types(cell: str) -> list[str]:
    """Типы товаров: перечисление через запятую."""
    return normalize_terms(cell.split(","))


def parse_money(cell: str) -> Decimal | None:
    """Читает денежную сумму. `None`, если ячейка не похожа на число.

    Принимает и запятую в роли десятичного разделителя, и пробелы-разделители
    разрядов: Google отдаёт значение так, как его отформатировала таблица
    пользователя, а не так, как удобно `Decimal`.
    """
    value = cell.strip()
    for separator in _THOUSAND_SEPARATORS:
        value = value.replace(separator, "")
    value = value.replace(",", ".")
    if value == "":
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def validate_category_rows(
    rows: Sequence[Sequence[str]],
    known_ids: set[int],
) -> str | None:
    """Проверяет лист `Categories`. `None` — можно писать в БД.

    Любая ошибка означает, что не будет записано **ничего**: лист правится
    целиком, и применить его половину — значит оставить справочник в состоянии,
    которого пользователь не задумывал.
    """
    if all(is_blank(row) for row in rows):
        return "Добавьте хотя бы одну категорию"

    ids: list[str] = []
    titles: list[str] = []
    aliases: list[str] = []
    product_types: list[str] = []

    for number, row in enumerate(rows, start=1):
        if is_blank(row):
            continue
        if is_cleared(row, CATEGORY_MEANINGFUL_FIELDS):
            error = _validate_known_id(row[0], known_ids, "категориях", number)
            if error is not None:
                return error
            ids.append(row[0].strip())
            continue

        error = _validate_known_id(row[0], known_ids, "категориях", number, optional=True)
        if error is not None:
            return error
        if row[0].strip() != "":
            ids.append(row[0].strip())
        if row[1] not in _FLAGS:
            return f"В категориях в {number} строке Active странный"
        if row[2] not in _FLAGS:
            return f"В категориях в {number} строке Income странный"
        if row[3] not in _FLAGS:
            return f"В категориях в {number} строке Cost странный"
        if row[2] == row[3]:
            return f"В категориях в {number} строке одинаковое значение у Income и Cost"
        if row[4].strip() == "":
            return f"В категориях в {number} строке Name пустой"
        if len(row[4].split()) > 1:
            return f"В категориях в {number} строке Name записан не одним словом"

        titles.append(row[4].strip().lower())
        aliases += parse_aliases(row[5], row[4])
        product_types += parse_product_types(row[6])

    if _has_duplicates(ids):
        return "В категориях один ID используется несколько раз"
    if _has_duplicates(titles):
        return "В категориях один name используется несколько раз"
    if _has_duplicates(aliases):
        return "В категориях один association используется несколько раз"
    if _has_duplicates(product_types):
        return "В категориях один product type используется несколько раз"
    return None


def validate_source_rows(
    rows: Sequence[Sequence[str]],
    known_ids: set[int],
) -> str | None:
    """Проверяет лист `Bills`. `None` — можно писать в БД."""
    if all(is_blank(row) for row in rows):
        return "Добавьте хотя бы один источник"

    ids: list[str] = []
    titles: list[str] = []
    aliases: list[str] = []

    for number, row in enumerate(rows, start=1):
        if is_blank(row):
            continue
        if is_cleared(row, SOURCE_MEANINGFUL_FIELDS):
            error = _validate_known_id(row[0], known_ids, "источниках", number)
            if error is not None:
                return error
            ids.append(row[0].strip())
            continue

        error = _validate_known_id(row[0], known_ids, "источниках", number, optional=True)
        if error is not None:
            return error
        if row[0].strip() != "":
            ids.append(row[0].strip())
        if row[1] not in _FLAGS:
            return f"В источниках в {number} строке Active странный"
        if row[2].strip() == "":
            return f"В источниках в {number} строке Name пустой"
        if len(row[2].split()) > 1:
            return f"В источниках в {number} строке Name записан не одним словом"
        if parse_money(row[4]) is None:
            return f"В источниках в {number} строке Balance не число"

        titles.append(row[2].strip().lower())
        aliases += parse_aliases(row[3], row[2])

    if _has_duplicates(ids):
        return "В источниках один ID используется несколько раз"
    if _has_duplicates(titles):
        return "В источниках один name используется несколько раз"
    if _has_duplicates(aliases):
        return "В источниках один association используется несколько раз"
    return None


def _validate_known_id(
    cell: str,
    known_ids: set[int],
    sheet: str,
    number: int,
    *,
    optional: bool = False,
) -> str | None:
    """Проверяет, что ID строки принадлежит этому документу.

    `optional` — пустой ID допустим и означает новую строку. У очищенной строки
    ID пустым быть не может: тогда удалять нечего.
    """
    value = cell.strip()
    if value == "" and optional:
        return None
    entity_id = parse_id(cell)
    if entity_id is None or entity_id not in known_ids:
        return f"В {sheet} в {number} строке неизвестный ID"
    return None


def _has_duplicates(values: Sequence[str]) -> bool:
    """Есть ли в наборе повторы."""
    return len(set(values)) != len(values)
