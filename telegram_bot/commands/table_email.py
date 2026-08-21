"""Команда `/table_email`: открыть доступ к таблице ещё одной почте."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.parsers import OnboardingParser, ParseError
from telegram_bot.resources.messages import ASK_ACCESS_EMAIL_MESSAGE, EMAIL_ADDED_MESSAGE
from telegram_bot.states import States


class TableEmailCommand(BaseCommand):
    """Спрашивает адрес и просит выдать ему доступ.

    Диалог начинает кнопка меню, продолжает — ответ пользователя. Разные входы
    и разные методы: `handle_callback` только задаёт вопрос и ставит состояние,
    `execute` регистрируется единственно под этим состоянием и разбирает ответ.

    Сам доступ выдаёт `google_sheets_service`; отказ Google (адрес не
    существует) приедет отдельным уведомлением, а не ответом на эту команду.
    """

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Дать доступ к таблице»: спрашивает почту."""
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, _ = target

        await self.aiogram.set_state(state, States.ADD_EMAIL)
        await self.aiogram.send_message(chat_id, ASK_ACCESS_EMAIL_MESSAGE)

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Ответ с почтой: выдаёт доступ."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(message, ASK_ACCESS_EMAIL_MESSAGE)
            return

        try:
            email = OnboardingParser.email(text)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        if email is None:
            # Пропуск на этом шаге равнозначен отказу от команды: выдавать
            # доступ некому.
            await self.aiogram.clear_state(state)
            await self.aiogram.answer_message(message, "Хорошо, доступ не выдаю")
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            await self.aiogram.clear_state(state)
            return

        await self.api.spreadsheets.add_email(spreadsheet.id, email)
        await self.aiogram.clear_state(state)
        await self.aiogram.answer_message(message, EMAIL_ADDED_MESSAGE.format(email=email))
