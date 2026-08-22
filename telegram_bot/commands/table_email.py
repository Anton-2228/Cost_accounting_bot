"""Команда `/table_email`: открыть доступ к таблице ещё одной почте."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.cancel import BRANCH_EMAIL, cancel_row
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
        await self._ask(chat_id, state)

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Ответ с почтой: выдаёт доступ."""
        chat_id = message.chat.id
        text = self.text_of(message)
        if text is None:
            await self._ask(chat_id, state)
            return

        try:
            email = OnboardingParser.email(text)
        except ParseError as error:
            await self.ask(
                chat_id=chat_id,
                state=state,
                text=error.message,
                rows=[cancel_row(BRANCH_EMAIL)],
            )
            return

        if email is None:
            # Пропуск на этом шаге равнозначен отказу от команды: выдавать
            # доступ некому.
            await self.finish(chat_id=chat_id, state=state)
            await self.aiogram.answer_message(message, "Хорошо, доступ не выдаю")
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            await self.finish(chat_id=chat_id, state=state)
            return

        await self.api.spreadsheets.add_email(spreadsheet.id, email)
        await self.finish(chat_id=chat_id, state=state)
        await self.aiogram.answer_message(message, EMAIL_ADDED_MESSAGE.format(email=email))

    async def _ask(self, chat_id: int, state: FSMContext) -> None:
        """Вопрос про почту с кнопкой выхода из ветки."""
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=ASK_ACCESS_EMAIL_MESSAGE,
            rows=[cancel_row(BRANCH_EMAIL)],
        )
