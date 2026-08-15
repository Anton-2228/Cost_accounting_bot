"""Команда `/table_sync`: вчитать справочники из листов."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.resources.messages import SYNC_REQUESTED_MESSAGE


class TableSyncCommand(BaseCommand):
    """Просит api вчитать листы `Categories` и `Bills` в базу.

    Ответ приходит сразу и означает только «задачу поставили»: лист читает
    `google_sheets_service` по очереди, и результат разбора — успех или русский
    текст с номером строки — приедет **уведомлением**.

    Состояние при этом не ставится. В старой версии неудачный разбор переводил
    пользователя в `CORRECT_TABLE`, откуда работала одна-единственная команда —
    сам `/sync`; пользователь с непочинимым листом терял доступ ко всему,
    включая удаление таблицы.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Ставит задачу на чтение листов."""
        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        await self.api.spreadsheets.request_sync(spreadsheet.id)
        await self.aiogram.answer_message(message, SYNC_REQUESTED_MESSAGE)
