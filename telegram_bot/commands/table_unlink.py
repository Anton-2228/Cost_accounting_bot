"""Команда `/table_delete`: отвязать таблицу от бота."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.resources.messages import (
    ASK_DELETE_CONFIRM_MESSAGE,
    DELETE_CANCELLED_MESSAGE,
    TABLE_DELETED_MESSAGE,
)
from telegram_bot.states import States

#: Слово подтверждения. Набрать его случайно нельзя — в этом и смысл.
CONFIRM_WORD = "ПОДТВЕРЖДАЮ УДАЛЕНИЕ"


class TableDeleteCommand(BaseCommand):
    """Удаляет данные учёта после явного подтверждения.

    Сам Google-документ остаётся у владельца: бот удаляет только то, чем
    владеет api. Об этом сказано в вопросе — иначе подтверждение давалось бы
    вслепую.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Первый вызов спрашивает подтверждение, второй — удаляет."""
        current = await self.aiogram.get_state(state)

        if current != States.CONFIRM_DELETE_TABLE.state:
            await self.aiogram.set_state(state, States.CONFIRM_DELETE_TABLE)
            await self.aiogram.answer_message(
                message, ASK_DELETE_CONFIRM_MESSAGE.format(word=CONFIRM_WORD)
            )
            return

        text = self.text_of(message)
        if text is None or text.strip() != CONFIRM_WORD:
            # Состояние снимается обязательно. Старая версия отвечала «удаление
            # отменено», но состояние оставляла, и следующее сообщение
            # пользователя снова трактовалось как подтверждение удаления.
            await self.aiogram.clear_state(state)
            await self.aiogram.answer_message(message, DELETE_CANCELLED_MESSAGE)
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            await self.aiogram.clear_state(state)
            return

        await self.api.spreadsheets.delete(spreadsheet.id)
        await self.aiogram.clear_state(state)
        await self.aiogram.answer_message(message, TABLE_DELETED_MESSAGE)
