"""Разбор и проверка строк листа `Categories`.

Отказ — не фраза, а :class:`api.domain.user_message.UserMessage`: код
`import_error.<что не так>` и данные для подстановки — номер строки, название
колонки. Фразу на языке пользователя («В категориях в 5 строке Active
странный») собирает бот по своему каталогу; русские формулировки там
унаследованы дословно.

Нумерация строк смещена на единицу относительно листа (диапазон начинается со
второй строки, а счёт идёт с первой) — пользователи привыкли к этим номерам,
поэтому смещение сохранено.

Отличия от старой версии чинят баги:

* Проверяется, что ID из строки существует в этом документе. Прежний код брал
  `by_id[int(row[0])]` без проверки, и опечатка в ID или строка, скопированная
  из чужой таблицы, роняли весь импорт с `KeyError`.
* Проверяется, что один ID не встречается в листе дважды. Скопированная строка
  иначе означала бы две несовместимые правки одной записи: какая из них
  победит, зависело бы от порядка строк, а строка «удалить» вместе со строкой
  «обновить» роняла импорт с `KeyError`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from api.core.text import normalize_terms
from api.domain.user_message import UserMessage

#: Колонки листа `Categories`: ID · Active · Income · Cost · Name · Associations · Product types
CATEGORY_WIDTH = 7

#: Сколько полей после ID означают «строку очистили» (пустые ⇒ удаление).
CATEGORY_MEANINGFUL_FIELDS = 6

_FLAGS = ("0", "1")

#: Колонки-флаги и их позиции в строке — в порядке, в котором они проверяются.
_FLAG_COLUMNS = (("Active", 1), ("Income", 2), ("Cost", 3))


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


def validate_category_rows(
    rows: Sequence[Sequence[str]],
    known_ids: set[int],
    *,
    defaults: Mapping[int, bool] | None = None,
) -> UserMessage | None:
    """Проверяет лист `Categories`. `None` — можно писать в БД.

    Любая ошибка означает, что не будет записано **ничего**: лист правится
    целиком, и применить его половину — значит оставить справочник в состоянии,
    которого пользователь не задумывал.

    `defaults` — категории по умолчанию: ID → «это доходная». Их можно
    переименовать, но нельзя удалить, выключить или перевести в другой вид:
    корзине расходов некуда было бы деться, а разбор чека остался бы без
    места, куда сложить неразложенное.
    """
    defaults = defaults or {}
    if all(is_blank(row) for row in rows):
        return _error("empty")

    ids: list[str] = []
    titles: list[str] = []
    aliases: list[str] = []
    product_types: list[str] = []

    for number, row in enumerate(rows, start=1):
        if is_blank(row):
            continue
        if is_cleared(row, CATEGORY_MEANINGFUL_FIELDS):
            error = _validate_known_id(row[0], known_ids, number)
            if error is not None:
                return error
            if parse_id(row[0]) in defaults:
                return _error("default_removed", row=number)
            ids.append(row[0].strip())
            continue

        error = _validate_known_id(row[0], known_ids, number, optional=True)
        if error is not None:
            return error
        if row[0].strip() != "":
            ids.append(row[0].strip())
        for column, index in _FLAG_COLUMNS:
            if row[index] not in _FLAGS:
                return _error("flag_invalid", row=number, column=column)
        if row[2] == row[3]:
            return _error("income_equals_cost", row=number)
        entity_id = parse_id(row[0])
        if entity_id is not None and entity_id in defaults:
            if row[1] != "1":
                return _error("default_deactivated", row=number)
            if (row[2] == "1") != defaults[entity_id]:
                return _error("default_kind_changed", row=number)
        if row[4].strip() == "":
            return _error("name_empty", row=number)
        if len(row[4].split()) > 1:
            return _error("name_not_one_word", row=number)

        titles.append(row[4].strip().lower())
        aliases += parse_aliases(row[5], row[4])
        product_types += parse_product_types(row[6])

    if _has_duplicates(ids):
        return _error("duplicate_id")
    if _has_duplicates(titles):
        return _error("duplicate_name")
    if _has_duplicates(aliases):
        return _error("duplicate_association")
    if _has_duplicates(product_types):
        return _error("duplicate_product_type")
    return None


def _error(code: str, **params: str | int) -> UserMessage:
    """Отказ импорта: код `import_error.<code>` и данные для подстановки."""
    return UserMessage(code=f"import_error.{code}", params=params)


def _validate_known_id(
    cell: str,
    known_ids: set[int],
    number: int,
    *,
    optional: bool = False,
) -> UserMessage | None:
    """Проверяет, что ID строки принадлежит этому документу.

    `optional` — пустой ID допустим и означает новую строку. У очищенной строки
    ID пустым быть не может: тогда удалять нечего.
    """
    value = cell.strip()
    if value == "" and optional:
        return None
    entity_id = parse_id(cell)
    if entity_id is None or entity_id not in known_ids:
        return _error("unknown_id", row=number)
    return None


def _has_duplicates(values: Sequence[str]) -> bool:
    """Есть ли в наборе повторы."""
    return len(set(values)) != len(values)
