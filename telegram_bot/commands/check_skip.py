"""Команда `/check_skip`: отложить текущий чек."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.check import CheckCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.resources.messages import CHECK_LOST_MESSAGE, CHECK_SKIPPED_MESSAGE


class CheckSkipCommand(BaseCommand):
    """Откладывает чек и показывает следующий.

    Не сохраняет ничего: чек остаётся `processed_at IS NULL` и вернётся в
    следующей сессии разбора. Список пропущенных живёт в FSM-данных ровно
    поэтому — без него «следующим» бесконечно оказывался бы тот же самый чек.
    """

    def __init__(
        self,
        manager: Manager,
        api: ApiGateway,
        aiogram_wrapper: AiogramWrapper,
        catch_up: NotificationCatchUp,
        check: CheckCommand,
    ) -> None:
        super().__init__(manager, api, aiogram_wrapper, catch_up)
        self.check = check

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Кладёт текущий чек в пропущенные и переходит к следующему."""
        draft = await self.check.current_draft(state)
        if draft is None:
            await self.aiogram.clear_state(state)
            await self.aiogram.answer_message(message, CHECK_LOST_MESSAGE)
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        await self.check.add_skipped(state, draft.check_id)
        await self.aiogram.answer_message(message, CHECK_SKIPPED_MESSAGE)
        await self.check.show_next(
            chat_id=message.chat.id,
            state=state,
            spreadsheet=spreadsheet,
        )
