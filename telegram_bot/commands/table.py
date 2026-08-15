"""Команда `/table`: ссылка на Google-документ."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.formatting import TableFormatter


class TableCommand(BaseCommand):
    """Печатает адрес документа.

    Ссылку бот собирает сам из `google_spreadsheet_id`, а не хранит: она
    выводится из идентификатора однозначно. Поэтому потерянное уведомление
    «таблица готова» не оставляет пользователя без адреса — он всегда доступен
    этой командой.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Отправляет ссылку или сообщает, что документ ещё создаётся."""
        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return
        await self.aiogram.answer_message(message, TableFormatter.link(spreadsheet))
