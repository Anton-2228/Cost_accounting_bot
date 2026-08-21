"""Команда `/table`: ссылка на Google-документ."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.formatting import TableFormatter


class TableCommand(BaseCommand):
    """Печатает адрес документа.

    Ссылку бот собирает сам из `google_spreadsheet_id`, а не хранит: она
    выводится из идентификатора однозначно. Поэтому потерянное уведомление
    «таблица готова» не оставляет пользователя без адреса — он всегда доступен
    кнопкой «Получить таблицу».
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Отправляет ссылку или сообщает, что документ ещё создаётся."""
        await self.show(chat_id=message.chat.id, telegram_id=self.user_id(message))

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Получить таблицу» в меню."""
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, telegram_id = target
        await self.show(chat_id=chat_id, telegram_id=telegram_id)

    async def show(self, *, chat_id: int, telegram_id: int) -> None:
        """Рисует ответ по явным идентификаторам.

        Работа идёт не по сообщению: нажатие кнопки приносит сообщение бота, а
        не пользователя, и искать таблицу по нему значило бы искать её по
        идентификатору самого бота.
        """
        spreadsheet = await self.spreadsheet_for(user_id=telegram_id, chat_id=chat_id)
        if spreadsheet is None:
            return
        await self.aiogram.send_message(chat_id, TableFormatter.link(spreadsheet))
