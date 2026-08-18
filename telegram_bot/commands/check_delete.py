"""Команда `/check_del`: удалить текущий чек."""

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
from telegram_bot.resources.messages import CHECK_DELETED_MESSAGE, CHECK_LOST_MESSAGE


class CheckDeleteCommand(BaseCommand):
    """Удаляет чек из очереди и показывает следующий.

    Подтверждения нет намеренно: удаляется то, что ещё ни во что не
    превратилось, и восстановить его можно повторным сканом той же бумажки —
    удаление в api мягкое, а уникальность ключа среди живых строк, поэтому
    удалённый чек её не занимает.

    Разобранный чек так не удалить — api ответит 409. Его убирают, удаляя его
    операции: с последней уходит и сам чек.
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
        """Удаляет текущий чек и переходит к следующему."""
        draft = await self.check.current_draft(state)
        if draft is None:
            await self.aiogram.clear_state(state)
            await self.aiogram.answer_message(message, CHECK_LOST_MESSAGE)
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        await self.api.checks.delete(spreadsheet.id, draft.check_id)
        await self.aiogram.answer_message(message, CHECK_DELETED_MESSAGE)
        await self.check.show_next(
            chat_id=message.chat.id,
            state=state,
            spreadsheet=spreadsheet,
        )
