"""Кнопка «Удалить»: убрать текущий чек из очереди."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.checks.draft import CheckDraft
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.check import CheckCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.enums import CommandName
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.resources.messages import (
    ASK_CHECK_DELETE_MESSAGE,
    CHECK_DELETED_MESSAGE,
    CHECK_LOST_MESSAGE,
    CHECK_STALE_BUTTON_MESSAGE,
)

#: Ответы на вопрос подтверждения. Едут в `callback_data` перед номером чека —
#: тот везде остаётся последним, и сверка «моя ли это кнопка» одна на все.
_CONFIRM = "yes"
_DECLINE = "no"

_CONFIRM_BUTTON = "Да, удалить"
_DECLINE_BUTTON = "Нет"


class CheckDeleteCommand(BaseCommand):
    """Удаляет чек из очереди и показывает следующий.

    Спрашивает подтверждение — в отличие от прежней команды `/check_del`,
    которая удаляла сразу. Причина в способе вызова, а не в цене ошибки:
    набрать команду случайно нельзя, а кнопка стоит вплотную к «Отложить», и
    промах между ними означал бы разные вещи — «вернётся в следующий раз» и
    «исчезло».

    Само удаление осталось прежним: мягкое, сырьё в базе остаётся, ключ среди
    живых строк освобождается, и ту же бумажку можно отсканировать заново.
    Разобранный чек так не удалить — api ответит 409; его убирают, удаляя его
    операции.
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
        raise NotImplementedError("«Удалить» — только кнопка")

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Спрашивает подтверждение, а по ответу удаляет либо возвращает стадию."""
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

        answer = self._answer(callback.data)
        if answer is None:
            await self._confirm(chat_id=chat_id, state=state, draft=draft)
            return
        if answer == _DECLINE:
            await self.check.show_stage(
                chat_id=chat_id,
                state=state,
                draft=draft,
                spreadsheet=spreadsheet,
            )
            return

        await self.api.checks.delete(spreadsheet.id, draft.check_id)
        await self.aiogram.send_message(chat_id, CHECK_DELETED_MESSAGE)
        await self.check.show_next(chat_id=chat_id, state=state, spreadsheet=spreadsheet)

    async def _confirm(self, *, chat_id: int, state: FSMContext, draft: CheckDraft) -> None:
        """Задаёт вопрос, заменяя клавиатуру стадии на «Да» и «Нет».

        Отдельного состояния FSM под вопрос не заводится: ответ приходит
        кнопкой, а `check_id` в её `callback_data` и так отвечает на вопрос «к
        чему это относится» точнее любого состояния. Стадия при этом не
        теряется — по ней и возвращается отказ.
        """
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=ASK_CHECK_DELETE_MESSAGE,
            rows=[
                (
                    (_CONFIRM_BUTTON, self._data(_CONFIRM, draft)),
                    (_DECLINE_BUTTON, self._data(_DECLINE, draft)),
                ),
            ],
        )

    @staticmethod
    def _data(answer: str, draft: CheckDraft) -> str:
        """`callback_data` кнопки ответа."""
        return f"{CommandName.CHECK_DEL}:{answer}:{draft.check_id}"

    @staticmethod
    def _answer(data: str | None) -> str | None:
        """Ответ на подтверждение или `None`, если его ещё не задавали.

        `check_del:<id>` — первое нажатие, вопрос ещё впереди;
        `check_del:yes:<id>` и `check_del:no:<id>` — ответ на него.
        """
        parts = (data or "").split(":")
        if len(parts) != 3:
            return None
        return parts[1] if parts[1] in {_CONFIRM, _DECLINE} else None
