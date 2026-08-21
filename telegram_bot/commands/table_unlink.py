"""Команда `/table_unlink`: отвязать таблицу от бота."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.resources.messages import (
    ASK_UNLINK_CONFIRM_MESSAGE,
    TABLE_UNLINKED_MESSAGE,
    UNLINK_CANCELLED_MESSAGE,
)
from telegram_bot.states import States

#: Слово подтверждения. Набрать его случайно нельзя — в этом и смысл.
CONFIRM_WORD = "ПОДТВЕРЖДАЮ ОТВЯЗЫВАНИЕ"


class TableUnlinkCommand(BaseCommand):
    """Отвязывает таблицу от бота после явного подтверждения.

    Вопрос задаёт кнопка меню, отвечает пользователь словом подтверждения:
    `handle_callback` ставит состояние, `execute` регистрируется единственно
    под ним и разбирает ответ.

    Сам Google-документ остаётся у владельца: бот отвязывает только то, чем
    владеет api. Об этом сказано в вопросе — иначе подтверждение давалось бы
    вслепую.
    """

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Отвязать таблицу от бота»: спрашивает подтверждение."""
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, _ = target

        await self.aiogram.set_state(state, States.CONFIRM_UNLINK_TABLE)
        await self.aiogram.send_message(
            chat_id, ASK_UNLINK_CONFIRM_MESSAGE.format(word=CONFIRM_WORD)
        )

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Ответ на вопрос: слово подтверждения отвязывает таблицу."""
        text = self.text_of(message)
        if text is None or text.strip() != CONFIRM_WORD:
            # Состояние снимается обязательно. Старая версия отвечала «удаление
            # отменено», но состояние оставляла, и следующее сообщение
            # пользователя снова трактовалось как подтверждение.
            await self.aiogram.clear_state(state)
            await self.aiogram.answer_message(message, UNLINK_CANCELLED_MESSAGE)
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            await self.aiogram.clear_state(state)
            return

        await self.api.spreadsheets.delete(spreadsheet.id)
        await self.aiogram.clear_state(state)
        await self.aiogram.answer_message(message, TABLE_UNLINKED_MESSAGE)
