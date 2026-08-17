"""Разбор правок к предложенному разбору чека.

Формат один на обе стадии: «номера позиций — значение», по строке на правку.

    1,3 - молочка
    2 - бытовая химия

Разбор возвращает модель либо бросает :class:`ParseError` с готовым русским
текстом. Протокол `{"status": "success"|"error"}`, которым старая версия
отвечала именно в разборе чека, не воспроизводится: в боте один способ сообщить
о неудачном вводе, и он тот же, что у `/add`.
"""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.parsers.results import ParsedCheckEdit, ParseError

_USAGE = (
    "Не понял правку. Нужно так: «1,3 - молочка», по строке на каждую правку.\n"
    "Если всё верно — нажмите «Готово»"
)


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
            raise ParseError(_USAGE)

        edits: list[ParsedCheckEdit] = []
        seen: set[int] = set()
        for line in lines:
            edit = cls._parse_line(line, count=count, max_value_length=max_value_length)
            repeated = seen.intersection(edit.numbers)
            if repeated:
                numbers = ", ".join(str(number) for number in sorted(repeated))
                raise ParseError(f"Позиция {numbers} указана дважды — оставьте одну правку")
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
        head, separator, tail = line.partition(constants.CHECK_EDIT_SEPARATOR)
        if not separator:
            raise ParseError(_USAGE)

        value = tail.strip()
        if not value:
            raise ParseError(_USAGE)
        if max_value_length is not None and len(value) > max_value_length:
            raise ParseError(f"Значение длиннее {max_value_length} символов")

        return ParsedCheckEdit(numbers=cls._numbers(head, count=count), value=value)

    @staticmethod
    def _numbers(raw: str, *, count: int) -> tuple[int, ...]:
        """Номера позиций из левой части строки."""
        normalized = raw
        for separator in constants.CHECK_NUMBER_SEPARATORS:
            normalized = normalized.replace(separator, " ")

        parts = normalized.split()
        if not parts:
            raise ParseError(_USAGE)

        numbers: list[int] = []
        for part in parts:
            if not part.isdigit():
                raise ParseError(_USAGE)
            number = int(part)
            if not 1 <= number <= count:
                raise ParseError(f"Позиции №{number} в чеке нет. Всего позиций: {count}")
            numbers.append(number)
        return tuple(dict.fromkeys(numbers))
