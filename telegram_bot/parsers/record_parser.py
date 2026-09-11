"""Разбор строки добавления операции."""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.api_client.models import Category, CategoryKind
from telegram_bot.i18n import t
from telegram_bot.parsers import currency_parser
from telegram_bot.parsers.amount_parser import AmountParser
from telegram_bot.parsers.association_matcher import AssociationMatcher
from telegram_bot.parsers.results import ParsedRecord, ParseError


class RecordParser:
    """Строка `валюта сумма категория [пометка...]` → :class:`ParsedRecord`.

    Порядок позиционный. Пометка — весь остаток строки, поэтому пробелы в ней
    разрешены, а в названии категории — нет: на то и заведены псевдонимы.

    Валюта обязательна и стоит **первой**. Обязательна она потому, что
    подставить её больше неоткуда: прежде без валюты операция записывалась в
    валюте счёта, а счетов в системе нет. Умолчание вроде «рубль, если не
    сказано иное» молча приписывало бы валюту той трате, где пользователь про
    неё просто забыл, и отличить её от названной было бы нечем.

    Место выбрано не из удобства: первое слово — либо валюта, либо мусор, и
    спутать её с суммой нельзя, ни одно написание валюты не разбирается как
    число. Стой валюта перед пометкой, границу «валюта или уже пометка»
    пришлось бы угадывать по содержимому слова, и пометка, начинающаяся со
    слова «евро», молча превращалась бы в валюту, укорачивая саму себя.
    """

    @classmethod
    def parse(cls, raw_args: str | None, *, categories: list[Category]) -> ParsedRecord:
        """Разбирает аргументы команды или бросает :class:`ParseError`."""
        parts = (raw_args or "").split()
        if len(parts) < constants.RECORD_ARGUMENTS:
            raise ParseError(t("parse.record.usage"))

        currency = currency_parser.parse(parts[0])
        if currency is None:
            raise ParseError(
                t(
                    "parse.record.bad_currency",
                    word=parts[0],
                    hint=currency_parser.hint(),
                    usage=t("parse.record.usage"),
                )
            )

        amount = AmountParser.parse(parts[1])

        category = AssociationMatcher.category(parts[2], categories)
        if category is None:
            hint = AssociationMatcher.hint([item.title for item in categories])
            raise ParseError(t("parse.category_not_found", value=parts[2], hint=hint))

        notes = " ".join(parts[constants.RECORD_ARGUMENTS :])
        if len(notes) > constants.NOTES_MAX_LENGTH:
            raise ParseError(t("parse.record.notes_too_long", limit=constants.NOTES_MAX_LENGTH))

        return ParsedRecord(
            amount=amount,
            currency=currency,
            category_id=category.id,
            category_title=category.title,
            category_is_income=category.kind is CategoryKind.INCOME,
            notes=notes,
        )
