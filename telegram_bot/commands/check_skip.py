"""Кнопка «Отложить»: отложить текущий чек."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.check import CheckCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.resources.messages import (
    CHECK_LOST_MESSAGE,
    CHECK_SKIPPED_MESSAGE,
    CHECK_STALE_BUTTON_MESSAGE,
)


class CheckSkipCommand(BaseCommand):
    """Откладывает чек и показывает следующий.

    Не сохраняет ничего: чек остаётся `processed_at IS NULL` и вернётся в
    следующей сессии разбора. Список пропущенных живёт в FSM-данных ровно
    поэтому — без него «следующим» бесконечно оказывался бы тот же самый чек.

    Команды `/check_skip` больше нет: она была осмысленна ровно внутри разбора
    и нигде больше, а набирать её приходилось посреди кнопочного диалога.
    Кнопка при этом ничего не потеряла — регистрация по-прежнему ограничена
    состояниями разбора.
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
        """Входа командой у этой ветки нет.

        Не заглушка «на всякий случай»: сюда можно попасть только ошибкой
        сборки — регистрацией кнопочной команды как текстовой, — и молчать о
        ней хуже, чем упасть.
        """
        raise NotImplementedError("«Отложить» — только кнопка")

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кладёт текущий чек в пропущенные и переходит к следующему."""
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, telegram_id = target

        draft = await self.check.current_draft(state)
        if draft is None:
            await self.finish(chat_id=chat_id, state=state)
            await self.aiogram.send_message(chat_id, CHECK_LOST_MESSAGE)
            return

        if not self.check.is_current(callback.data, draft):
            await self.aiogram.send_message(chat_id, CHECK_STALE_BUTTON_MESSAGE)
            return

        spreadsheet = await self.spreadsheet_for(user_id=telegram_id, chat_id=chat_id)
        if spreadsheet is None:
            return

        await self.check.add_skipped(state, draft.check_id)
        await self.aiogram.send_message(chat_id, CHECK_SKIPPED_MESSAGE)
        await self.check.show_next(chat_id=chat_id, state=state, spreadsheet=spreadsheet)
