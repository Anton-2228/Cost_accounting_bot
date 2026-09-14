"""Разбор правок к предложенному разбору чека.

Формат один на обе стадии: «номера позиций — значение», по строке на правку.

    1,3 - молочка
    2 - бытовая химия

Строка, начатая с «!», не назначает значение, а убирает позиции из записи:

    !4,5

Обе формы живут в одном сообщении вперемешку и разбираются одним проходом:
проверка «позиция указана дважды» обязана видеть их вместе, иначе «!1» и
«1 - молочка» рядом означали бы неизвестно что.

Разбор возвращает модель либо бросает :class:`ParseError` с готовым текстом.
Протокол `{"status": "success"|"error"}`, которым старая версия
отвечала именно в разборе чека, не воспроизводится: в боте один способ сообщить
о неудачном вводе, и он тот же, что у `/add`.
"""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.i18n import t
from telegram_bot.parsers.results import ParsedCheckEdit, ParseError


def _usage() -> ParseError:
    """Отказ «не понял правку» с образцом ввода."""
    return ParseError(t("parse.check.usage"))


class CheckParser:
    """Строки «номера - значение» → список правок."""

    @classmethod
    def parse(
        cls,
        text: str | None,
        *,
        count: int,
        max_value_length: int | None = None,
    ) -> list[ParsedCheckEdit]:
        """Разбирает ввод или бросает :class:`ParseError`.

        `count` — сколько позиций показано пользователю. Номер вне этого
        диапазона отвергается здесь, а не молча пропускается: «правка не
        применилась и никто не сказал почему» — ровно то поведение, из-за
        которого правки в старой версии терялись.
        """
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            raise _usage()

        edits: list[ParsedCheckEdit] = []
        seen: set[int] = set()
        for line in lines:
            edit = cls._parse_line(line, count=count, max_value_length=max_value_length)
            repeated = seen.intersection(edit.numbers)
            if repeated:
                numbers = ", ".join(str(number) for number in sorted(repeated))
                raise ParseError(t("parse.check.repeated", numbers=numbers))
            seen.update(edit.numbers)
            edits.append(edit)
        return edits

    @classmethod
    def _parse_line(
        cls,
        line: str,
        *,
        count: int,
        max_value_length: int | None,
    ) -> ParsedCheckEdit:
        """Разбирает одну строку правки."""
        if line.startswith(constants.CHECK_DELETE_PREFIX):
            return cls._parse_delete(line, count=count)

        head, separator, tail = line.partition(constants.CHECK_EDIT_SEPARATOR)
        if not separator:
            raise _usage()

        value = tail.strip()
        if not value:
            raise _usage()
        if max_value_length is not None and len(value) > max_value_length:
            raise ParseError(t("parse.check.value_too_long", limit=max_value_length))

        return ParsedCheckEdit(numbers=cls._numbers(head, count=count), value=value)

    @classmethod
    def _parse_delete(cls, line: str, *, count: int) -> ParsedCheckEdit:
        """Разбирает строку удаления: «!1,2,13».

        Значения такая строка не принимает: «!1 - молочка» одинаково читается и
        как «удалить», и как «назначить тип», и принять её значило бы выбрать
        за пользователя одно из двух. Номера разбираются тем же `_numbers`, что
        и у обычной правки, — вместе с проверкой диапазона и разделителями.
        """
        numbers = line[len(constants.CHECK_DELETE_PREFIX) :]
        if constants.CHECK_EDIT_SEPARATOR in numbers:
            raise _usage()
        return ParsedCheckEdit(numbers=cls._numbers(numbers, count=count), delete=True)

    @staticmethod
    def _numbers(raw: str, *, count: int) -> tuple[int, ...]:
        """Номера позиций из левой части строки."""
        normalized = raw
        for separator in constants.CHECK_NUMBER_SEPARATORS:
            normalized = normalized.replace(separator, " ")

        parts = normalized.split()
        if not parts:
            raise _usage()

        numbers: list[int] = []
        for part in parts:
            if not part.isdigit():
                raise _usage()
            number = int(part)
            if not 1 <= number <= count:
                raise ParseError(t("parse.check.no_position", number=number, count=count))
            numbers.append(number)
        return tuple(dict.fromkeys(numbers))
