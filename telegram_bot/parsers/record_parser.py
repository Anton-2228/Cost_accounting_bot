"""Разбор строки добавления операции."""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.api_client.models import Category, CategoryKind, Source
from telegram_bot.parsers import currency_parser
from telegram_bot.parsers.amount_parser import AmountParser
from telegram_bot.parsers.association_matcher import AssociationMatcher
from telegram_bot.parsers.results import ParsedRecord, ParseError

_USAGE = "Нужно так: /add сумма категория счёт валюта пометка"


class RecordParser:
    """Строка `сумма категория счёт валюта [пометка...]` → :class:`ParsedRecord`.

    Порядок позиционный, сумма всегда первая. Пометка — весь остаток строки,
    поэтому пробелы в ней разрешены, а в названии категории, счёта и валюты —
    нет: для первых двух на то и заведены псевдонимы, а валюта пишется одним
    словом по определению.

    Валюта обязательна, хотя чаще всего совпадает с валютой счёта. Сделать её
    необязательной значило бы отличать «валюту» от «начала пометки» по
    содержимому слова, и пометка, начинающаяся со слова «евро», молча
    превращалась бы в валюту, укорачивая саму себя.
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
        if len(parts) < constants.RECORD_ARGUMENTS:
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

        currency = currency_parser.parse(parts[3])
        if currency is None:
            raise ParseError(
                f"Валюту «{parts[3]}» не понял.\nМожно так: {currency_parser.HINT}"
            )

        notes = " ".join(parts[constants.RECORD_ARGUMENTS :])
        if len(notes) > constants.NOTES_MAX_LENGTH:
            raise ParseError(f"Пометка длиннее {constants.NOTES_MAX_LENGTH} символов")

        return ParsedRecord(
            amount=amount,
            currency=currency,
            category_id=category.id,
            category_title=category.title,
            category_is_income=category.kind is CategoryKind.INCOME,
            source_id=source.id,
            source_title=source.title,
            notes=notes,
        )
