"""Разбор строки добавления операции."""

from __future__ import annotations

from decimal import Decimal

from telegram_bot import constants
from telegram_bot.api_client.models import Category, CategoryKind, Source
from telegram_bot.parsers import currency_parser
from telegram_bot.parsers.amount_parser import AmountParser
from telegram_bot.parsers.association_matcher import AssociationMatcher
from telegram_bot.parsers.results import NotANumberError, ParsedRecord, ParseError

_USAGE = "Нужно так: /add [валюта] сумма категория счёт пометка"


class RecordParser:
    """Строка `[валюта] сумма категория счёт [пометка...]` → :class:`ParsedRecord`.

    Порядок позиционный. Пометка — весь остаток строки, поэтому пробелы в ней
    разрешены, а в названии категории и счёта — нет: на то и заведены псевдонимы.

    Валюта необязательна и стоит **первой**. Место выбрано не из удобства, а
    потому, что только на нём необязательность вообще возможна: первое слово —
    либо валюта, либо сумма, и спутать их нельзя, ни одно написание валюты не
    разбирается как число. Стой валюта перед пометкой, как раньше, границу
    «валюта или уже пометка» пришлось бы угадывать по содержимому слова, и
    пометка, начинающаяся со слова «евро», молча превращалась бы в валюту,
    укорачивая саму себя.

    Без валюты операция записывается в валюте счёта — то самое, что нужно почти
    всегда. Значение берётся из уже найденного счёта, поэтому лишнего запроса
    оно не стоит.
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

        currency = currency_parser.parse(parts[0]) if parts else None
        offset = 1 if currency is not None else 0
        if len(parts) - offset < constants.RECORD_ARGUMENTS:
            raise ParseError(_USAGE)

        amount = cls._amount(parts[offset], currency_given=currency is not None)

        category = AssociationMatcher.category(parts[offset + 1], categories)
        if category is None:
            hint = AssociationMatcher.hint([item.title for item in categories])
            raise ParseError(
                f"Категории «{parts[offset + 1]}» нет, либо она выключена.\n"
                f"Есть такие: {hint}"
            )

        source = AssociationMatcher.source(parts[offset + 2], sources)
        if source is None:
            hint = AssociationMatcher.hint([item.title for item in sources])
            raise ParseError(
                f"Счёта «{parts[offset + 2]}» нет, либо он выключен.\nЕсть такие: {hint}"
            )

        if currency is None:
            currency = source.currency

        notes = " ".join(parts[offset + constants.RECORD_ARGUMENTS :])
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

    @staticmethod
    def _amount(raw: str, *, currency_given: bool) -> Decimal:
        """Сумма с поправкой на то, что на её месте могли иметь в виду валюту.

        Нераспознанное первое слово — единственный случай, когда пользователь
        мог промахнуться мимо обеих развилок сразу: написать «евра» вместо
        «евро». Тогда ошибка называет обе. Если валюта уже указана явно, слово
        на этом месте — заведомо сумма, и звать проверить валюту незачем.
        """
        try:
            return AmountParser.parse(raw)
        except NotANumberError:
            if currency_given:
                raise
            raise ParseError(
                f"«{raw}» не похоже ни на сумму, ни на валюту.\n"
                f"Валюту можно так: {currency_parser.HINT}\n{_USAGE}"
            ) from None
