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
    """`валюта сумма категория [пометка...]` одной строкой.

    Валюта обязательна: подставить её больше неоткуда, а умолчание молча
    приписывало бы валюту той трате, где пользователь про неё забыл.

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

        try:
            parsed = RecordParser.parse(
                command.args if command else None,
                categories=categories,
            )
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        record = await self.api.records.create(
            spreadsheet.id,
            category_id=parsed.category_id,
            amount=parsed.amount,
            currency=parsed.currency,
            notes=parsed.notes,
        )
        await self.aiogram.answer_message(message, RecordFormatter.saved(parsed, record))
