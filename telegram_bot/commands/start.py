"""Команда `/start`: мастер создания учётной таблицы."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot import constants
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.enums import CommandName, FsmDataKeys
from telegram_bot.formatting import TableFormatter
from telegram_bot.parsers import OnboardingParser, ParseError
from telegram_bot.parsers.onboarding_parser import SKIP_MARKERS
from telegram_bot.resources.messages import (
    ASK_EMAIL_MESSAGE,
    ASK_RESET_DAY_MESSAGE,
    ASK_TIMEZONE_MESSAGE,
    ASK_TITLE_MESSAGE,
    CREATING_TABLE_MESSAGE,
)
from telegram_bot.states import States


class StartCommand(BaseCommand):
    """Четыре шага: название → день сброса → часовой пояс → почта.

    Диалог разбирается внутри одной команды, а не разнесён по обработчикам:
    шаги связаны, и держать их рядом — единственный способ увидеть переход
    целиком. Ветвление идёт по текущему состоянию FSM.

    Промежуточные ответы живут в FSM-данных и больше нигде: они переживают
    перезапуск бота вместе с состоянием, и рассинхронизироваться им не с чем.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Ведёт пользователя по шагам мастера."""
        current = await self.aiogram.get_state(state)

        if current is None:
            await self._start(message, state)
        elif current == States.CREATE_TABLE_TITLE.state:
            await self._on_title(message, state)
        elif current == States.CREATE_TABLE_RESET_DAY.state:
            await self._on_reset_day(message, state)
        elif current == States.CREATE_TABLE_TIMEZONE.state:
            await self._on_timezone(message, state)
        elif current == States.CREATE_TABLE_EMAIL.state:
            await self._on_email(message, state)

    async def _start(self, message: Message, state: FSMContext) -> None:
        """Первый шаг. Наличие таблицы проверяет api — здесь только вопрос."""
        await self.aiogram.set_state(state, States.CREATE_TABLE_TITLE)
        await self.aiogram.answer_message(message, ASK_TITLE_MESSAGE)

    async def _on_title(self, message: Message, state: FSMContext) -> None:
        """Название таблицы."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(message, ASK_TITLE_MESSAGE)
            return
        try:
            title = OnboardingParser.title(text)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        await self.aiogram.set_state_data(state, FsmDataKeys.TITLE, title)
        await self.aiogram.set_state(state, States.CREATE_TABLE_RESET_DAY)
        await self.aiogram.answer_message(message, ASK_RESET_DAY_MESSAGE)

    async def _on_reset_day(self, message: Message, state: FSMContext) -> None:
        """День перехода на новый учётный месяц."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(message, ASK_RESET_DAY_MESSAGE)
            return
        try:
            reset_day = OnboardingParser.reset_day(text)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        await self.aiogram.set_state_data(state, FsmDataKeys.RESET_DAY, reset_day)
        await self.aiogram.set_state(state, States.CREATE_TABLE_TIMEZONE)
        await self.aiogram.answer_message(
            message, ASK_TIMEZONE_MESSAGE.format(default=constants.DEFAULT_TIMEZONE)
        )

    async def _on_timezone(self, message: Message, state: FSMContext) -> None:
        """Часовой пояс: от него зависят и дата операции, и момент ролловера."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(
                message, ASK_TIMEZONE_MESSAGE.format(default=constants.DEFAULT_TIMEZONE)
            )
            return

        raw = text.strip()
        if raw.lower() in SKIP_MARKERS:
            timezone = constants.DEFAULT_TIMEZONE
        else:
            try:
                timezone = OnboardingParser.timezone(raw)
            except ParseError as error:
                await self.aiogram.answer_message(message, error.message)
                return

        await self.aiogram.set_state_data(state, FsmDataKeys.TIMEZONE, timezone)
        await self.aiogram.set_state(state, States.CREATE_TABLE_EMAIL)
        await self.aiogram.answer_message(message, ASK_EMAIL_MESSAGE)

    async def _on_email(self, message: Message, state: FSMContext) -> None:
        """Последний шаг: почта (её можно пропустить) и создание таблицы."""
        text = self.text_of(message)
        if text is None:
            await self.aiogram.answer_message(message, ASK_EMAIL_MESSAGE)
            return
        try:
            email = OnboardingParser.email(text)
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        data = await state.get_data()
        title = str(data.get(FsmDataKeys.TITLE, ""))
        reset_day = int(data.get(FsmDataKeys.RESET_DAY, constants.MIN_RESET_DAY))
        timezone = str(data.get(FsmDataKeys.TIMEZONE, constants.DEFAULT_TIMEZONE))

        await self.aiogram.answer_message(message, CREATING_TABLE_MESSAGE)

        spreadsheet = await self.api.spreadsheets.create(
            telegram_id=self.user_id(message),
            title=title,
            reset_day=reset_day,
            timezone=timezone,
            email=email,
        )

        # Состояние снимается только после успеха: упади создание, пользователь
        # останется на последнем шаге и сможет повторить, не набирая заново
        # название, день и пояс.
        await self.aiogram.clear_state(state)
        await self.aiogram.answer_message(message, TableFormatter.link(spreadsheet))
        await self.manager.launch(CommandName.HELP, message, state)
