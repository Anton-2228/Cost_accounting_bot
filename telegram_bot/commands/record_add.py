"""Команда `/add`: добавление операции."""

from __future__ import annotations

from typing import Any

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.formatting import RecordFormatter
from telegram_bot.parsers import ParseError, RecordParser


class RecordAddCommand(BaseCommand):
    """`сумма категория счёт [пометка...]` одной строкой.

    Знак суммы не спрашивается и не принимается: расход это или доход,
    определяет вид категории. Так пользователь не может ошибиться знаком, а
    api — получить перевёрнутую операцию.

    Дата не спрашивается тоже — её ставит api по часовому поясу документа.
    Ввода задним числом нет: закрытый период не меняется.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Разбирает строку и записывает операцию."""
        command: CommandObject | None = kwargs.get("command")

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        categories = await self.api.catalog.categories(spreadsheet.id)
        sources = await self.api.catalog.sources(spreadsheet.id)

        try:
            parsed = RecordParser.parse(
                command.args if command else None,
                categories=categories,
                sources=sources,
            )
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        record = await self.api.records.create(
            spreadsheet.id,
            category_id=parsed.category_id,
            source_id=parsed.source_id,
            amount=parsed.amount,
            currency=parsed.currency,
            notes=parsed.notes,
        )
        await self.aiogram.answer_message(message, RecordFormatter.saved(parsed, record))
