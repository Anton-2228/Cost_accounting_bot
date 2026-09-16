"""Разбор строки добавления операции."""

from __future__ import annotations

from datetime import date

from telegram_bot import constants
from telegram_bot.api_client.models import Category, CategoryKind, Period
from telegram_bot.i18n import t
from telegram_bot.parsers import currency_parser
from telegram_bot.parsers.amount_parser import AmountParser
from telegram_bot.parsers.association_matcher import AssociationMatcher
from telegram_bot.parsers.day_parser import DayParser
from telegram_bot.parsers.results import ParsedRecord, ParseError


class RecordParser:
    """Строка `[день] валюта сумма категория [пометка...]` → :class:`ParsedRecord`.

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

    Датировать можно прошедшим днём периода и сегодняшним, но не завтрашним:
    почему — в :mod:`telegram_bot.parsers.day_parser`.

    День необязателен и стоит **перед** валютой — по той же причине, по какой
    валюта стоит перед пометкой: в конце строки его пришлось бы отличать от
    пометки по содержимому, и «/add евро 20 еда 10» датировалось бы десятым
    числом вместо того, чтобы запомнить «10». Формат общий со стадией дня в
    `/check` — голое число месяца внутри текущего периода, см.
    :class:`~telegram_bot.parsers.day_parser.DayParser`.

    Спутать день с валютой нельзя: ни одно написание валюты не состоит из
    цифр. Расплата за формат без сигила — строка, начатая суммой по привычке
    («/add 20 евро еда»), теперь спотыкается о слово «еда» на месте суммы, а не
    о «20» на месте валюты. Ошибкой она была и раньше.
    """

    @staticmethod
    def starts_with_day(raw_args: str | None) -> bool:
        """Начинается ли строка с дня.

        Нужен команде до разбора: границы периода за ним ехать в api, и ходить
        туда на каждый `/add` — самую частую команду бота — незачем. Решение
        «это день» тут ровно одно и на оба места: разойдись предикат с
        :meth:`parse`, команда либо не привезла бы период, либо возила бы его
        впустую.
        """
        parts = (raw_args or "").split()
        return bool(parts) and DayParser.looks_like_day(parts[0])

    @classmethod
    def parse(
        cls,
        raw_args: str | None,
        *,
        categories: list[Category],
        period: Period | None = None,
        today: date | None = None,
    ) -> ParsedRecord:
        """Разбирает аргументы команды или бросает :class:`ParseError`.

        `period` и `today` обязательны ровно тогда, когда
        :meth:`starts_with_day` сказала «да»: без границ день в дату не
        превратить, а без сегодняшнего дня документа — не отличить вчерашнюю
        трату от ненаступившей.
        """
        parts = (raw_args or "").split()

        added_at: date | None = None
        if parts and DayParser.looks_like_day(parts[0]):
            assert period is not None, "день в строке есть, а границы периода не привезли"
            assert today is not None, "день в строке есть, а сегодняшний день не привезли"
            added_at = DayParser.parse(
                parts[0],
                start_date=period.start_date,
                end_date=period.end_date,
                today=today,
            )
            parts = parts[1:]

        # Счёт слов — после того, как день снят: иначе «/add 3 евро» жаловалось
        # бы на валюту «3», а не на то, что строка не дописана.
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
            added_at=added_at,
        )
