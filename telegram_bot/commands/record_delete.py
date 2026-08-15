"""Команда `/del`: удаление операции."""

from __future__ import annotations

from typing import Any

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.formatting import RecordFormatter


class RecordDeleteCommand(BaseCommand):
    """`/del [id]` — без аргумента удаляет последнюю операцию периода.

    Идентификатор пользователь берёт из ответа на `/add`: списка
    операций в боте нет, отчётная поверхность — сама таблица.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Удаляет операцию по id или последнюю."""
        command: CommandObject | None = kwargs.get("command")
        raw = (command.args or "").strip() if command else ""

        record_id: int | None = None
        if raw:
            try:
                record_id = int(raw.split()[0])
            except ValueError:
                await self.aiogram.answer_message(
                    message, f"«{raw}» не похоже на id. Нужно так: /del 42"
                )
                return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        record = (
            await self.api.records.delete(spreadsheet.id, record_id)
            if record_id is not None
            else await self.api.records.delete_last(spreadsheet.id)
        )

        categories = await self.api.catalog.categories(spreadsheet.id, only_active=False)
        sources = await self.api.catalog.sources(spreadsheet.id, only_active=False)
        await self.aiogram.answer_message(
            message,
            RecordFormatter.deleted(record, categories=categories, sources=sources),
        )
