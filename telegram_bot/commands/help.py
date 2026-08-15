"""Команда `/help`: справка по боту."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.resources.messages import HELP_COMMANDS_MESSAGE, HELP_MESSAGE


class HelpCommand(BaseCommand):
    """Печатает описание работы и список команд.

    Двумя сообщениями, а не одним: описание таблицы длинное, и вместе со
    списком команд они не помещаются в лимит Telegram.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Отправляет справку."""
        await self.aiogram.answer_message(message, HELP_MESSAGE)
        await self.aiogram.answer_message(message, HELP_COMMANDS_MESSAGE)
