"""Разбор строки добавления операции."""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.api_client.models import Category, CategoryKind, Source
from telegram_bot.parsers.amount_parser import AmountParser
from telegram_bot.parsers.association_matcher import AssociationMatcher
from telegram_bot.parsers.results import ParsedRecord, ParseError

_USAGE = "Нужно так: /add сумма категория счёт пометка"


class RecordParser:
    """Строка `сумма категория счёт [пометка...]` → :class:`ParsedRecord`.

    Порядок позиционный, сумма всегда первая. Пометка — весь остаток строки,
    поэтому пробелы в ней разрешены, а в названии категории и счёта — нет: для
    них на то и заведены псевдонимы.
    """

    @classmethod
    def parse(
        cls,
        raw_args: str | None,
        *,
        categories: list[Category],
        sources: list[Source],
    ) -> ParsedRecord:
        """Разбирает аргументы команды или бросает :class:`ParseError`."""
        parts = (raw_args or "").split()
        if len(parts) < constants.REQUIRED_ARGUMENTS:
            raise ParseError(_USAGE)

        amount = AmountParser.parse(parts[0])

        category = AssociationMatcher.category(parts[1], categories)
        if category is None:
            hint = AssociationMatcher.hint([item.title for item in categories])
            raise ParseError(
                f"Категории «{parts[1]}» нет, либо она выключена.\nЕсть такие: {hint}"
            )

        source = AssociationMatcher.source(parts[2], sources)
        if source is None:
            hint = AssociationMatcher.hint([item.title for item in sources])
            raise ParseError(f"Счёта «{parts[2]}» нет, либо он выключен.\nЕсть такие: {hint}")

        notes = " ".join(parts[constants.REQUIRED_ARGUMENTS :])
        if len(notes) > constants.NOTES_MAX_LENGTH:
            raise ParseError(f"Пометка длиннее {constants.NOTES_MAX_LENGTH} символов")

        return ParsedRecord(
            amount=amount,
            category_id=category.id,
            category_title=category.title,
            category_is_income=category.kind is CategoryKind.INCOME,
            source_id=source.id,
            source_title=source.title,
            notes=notes,
        )
