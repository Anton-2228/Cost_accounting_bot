"""Команда `/table_sync`: вчитать справочники из листов."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

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
        await self.request(chat_id=message.chat.id, telegram_id=self.user_id(message))

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Синхронизировать таблицу» в меню."""
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, telegram_id = target
        await self.request(chat_id=chat_id, telegram_id=telegram_id)

    async def request(self, *, chat_id: int, telegram_id: int) -> None:
        """Ставит задачу по явным идентификаторам."""
        spreadsheet = await self.spreadsheet_for(user_id=telegram_id, chat_id=chat_id)
        if spreadsheet is None:
            return

        await self.api.spreadsheets.request_sync(spreadsheet.id)
        await self.aiogram.send_message(chat_id, SYNC_REQUESTED_MESSAGE)
