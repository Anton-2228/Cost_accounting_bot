"""Разбор строки перевода между счетами."""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.api_client.models import Source
from telegram_bot.parsers.amount_parser import AmountParser
from telegram_bot.parsers.association_matcher import AssociationMatcher
from telegram_bot.parsers.results import ParsedTransfer, ParseError

_USAGE = "Нужно так: /add_trans сумма откуда куда пометка"


class TransferParser:
    """Строка `сумма откуда куда [пометка...]` → :class:`ParsedTransfer`."""

    @classmethod
    def parse(cls, raw_args: str | None, *, sources: list[Source]) -> ParsedTransfer:
        """Разбирает аргументы команды или бросает :class:`ParseError`."""
        parts = (raw_args or "").split()
        if len(parts) < constants.TRANSFER_ARGUMENTS:
            raise ParseError(_USAGE)

        amount = AmountParser.parse(parts[0])
        hint = AssociationMatcher.hint([item.title for item in sources])

        sender = AssociationMatcher.source(parts[1], sources)
        if sender is None:
            raise ParseError(
                f"Счёта отправителя «{parts[1]}» нет, либо он выключен.\nЕсть такие: {hint}"
            )

        receiver = AssociationMatcher.source(parts[2], sources)
        if receiver is None:
            raise ParseError(
                f"Счёта получателя «{parts[2]}» нет, либо он выключен.\nЕсть такие: {hint}"
            )

        if sender.id == receiver.id:
            # Api ответил бы 422, но ошибка ввода очевидна здесь и объясняется
            # понятнее, чем «Счёт отправителя совпадает с получателем» после
            # круга по сети.
            raise ParseError("Счёт отправителя и получателя совпадают")

        notes = " ".join(parts[constants.TRANSFER_ARGUMENTS :])
        if len(notes) > constants.NOTES_MAX_LENGTH:
            raise ParseError(f"Пометка длиннее {constants.NOTES_MAX_LENGTH} символов")

        return ParsedTransfer(
            amount=amount,
            from_source_id=sender.id,
            from_source_title=sender.title,
            to_source_id=receiver.id,
            to_source_title=receiver.title,
            notes=notes,
        )
