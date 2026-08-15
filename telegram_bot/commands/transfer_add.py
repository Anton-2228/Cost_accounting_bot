"""Команда `/add_trans`: перевод между счетами."""

from __future__ import annotations

from typing import Any

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.formatting import TransferFormatter
from telegram_bot.parsers import ParseError, TransferParser


class TransferAddCommand(BaseCommand):
    """`сумма откуда куда [пометка...]` одной строкой.

    Перевод не доход и не расход: деньги не появились и не исчезли, изменились
    только балансы двух счетов. В отчёт он попадает одной строкой реестра.

    Пометка передаётся в api — в старой версии её просто не отправляли, и
    смысл перевода терялся.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Разбирает строку и записывает перевод."""
        command: CommandObject | None = kwargs.get("command")

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        sources = await self.api.catalog.sources(spreadsheet.id)

        try:
            parsed = TransferParser.parse(command.args if command else None, sources=sources)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        transfer = await self.api.transfers.create(
            spreadsheet.id,
            from_source_id=parsed.from_source_id,
            to_source_id=parsed.to_source_id,
            amount=parsed.amount,
            notes=parsed.notes,
        )
        await self.aiogram.answer_message(message, TransferFormatter.saved(parsed, transfer))
