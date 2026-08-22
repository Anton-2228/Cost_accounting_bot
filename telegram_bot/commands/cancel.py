"""Выход из диалога: кнопка «Отмена» и объяснение, почему иначе нельзя.

Одна команда на оба случая. Отмена и подсказка «сейчас идёт другой диалог» —
это один и тот же вопрос «как отсюда выйти», заданный с разных сторон, и
разнесённые по двум местам они разошлись бы первой же новой веткой: подсказка
предлагала бы выход, которого у ветки нет, либо молчала бы о том, который есть.
"""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.enums import CommandName
from telegram_bot.resources.messages import (
    CANCEL_STALE_MESSAGE,
    CANCELLED_MESSAGE,
    DIALOG_IN_PROGRESS_MESSAGE,
    DIALOG_IN_PROGRESS_NO_EXIT_MESSAGE,
)
from telegram_bot.states import States

#: Надпись кнопки. Одна на все ветки: «Отмена» значит одно и то же везде, и
#: разные слова для одного действия пришлось бы заучивать.
CANCEL_BUTTON_TEXT = "Отмена"

#: Метки веток в `callback_data`. Короткие и свои, а не строка состояния:
#: `States.ADD_EMAIL.state` — это «States:ADD_EMAIL», и двоеточие внутри
#: развалило бы разбор `callback_data`, который сам разделён двоеточиями.
BRANCH_EMAIL = "email"
BRANCH_UNLINK = "unlink"
BRANCH_LLM = "llm"
BRANCH_CHECK = "check"

#: Метка ветки → состояния, в которых её кнопка законна.
#:
#: Мастера создания таблицы здесь нет намеренно: кнопки «Отмена» он не несёт, и
#: выход из него один — набранный `/start`.
_BRANCH_STATES: dict[str, tuple[State, ...]] = {
    BRANCH_EMAIL: (States.ADD_EMAIL,),
    BRANCH_UNLINK: (States.CONFIRM_UNLINK_TABLE,),
    BRANCH_LLM: (States.SETTINGS_ASK_TELEGRAM_ID,),
    BRANCH_CHECK: (States.CHECK_TYPES, States.CHECK_CATEGORIES, States.CHECK_SOURCE),
}

#: Обратное отображение, чтобы по текущему состоянию узнать ветку. Считается
#: один раз на импорте: второй таблицы соответствий, которую надо держать
#: синхронной вручную, из-за этого не появляется.
_STATE_BRANCHES: dict[str, str] = {
    item.state: branch
    for branch, states in _BRANCH_STATES.items()
    for item in states
    if item.state is not None
}


def cancel_row(branch: str) -> tuple[tuple[str, str], ...]:
    """Ряд из одной кнопки «Отмена» для указанной ветки.

    Ветка едет в `callback_data`, потому что кнопка живёт в переписке дольше
    своего диалога: без метки нажатая через неделю кнопка от почты снесла бы
    недоразобранный чек. Тот же приём, что у кнопки «Готово» с `check_id`.
    """
    return ((CANCEL_BUTTON_TEXT, f"{CommandName.CANCEL}:{branch}"),)


class CancelCommand(BaseCommand):
    """Выпускает из диалога и объясняет, что выход именно здесь.

    Команды `/cancel` больше нет. Причина не в лишней строке меню: пользователь
    отвечает боту кнопками, и требование вспомнить и набрать слово посреди
    кнопочного диалога — единственное место, где интерфейс менялся на ходу.

    Взамен ослаб инвариант «выход есть всегда и он один»: сообщение с кнопкой
    можно пролистать или удалить у себя. Поэтому выходов теперь два, и второй
    не требует ничего помнить — набранный `/start` чистит состояние в любой
    ветке.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Команда, набранная посреди диалога: подсказка про выход.

        Разбирать её как ответ на вопрос шага нельзя — ровно это делала старая
        версия, и `/table` внутри мастера получал «Странный ввод».
        """
        await self.hint(chat_id=message.chat.id, state=state)

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Нажатие кнопки: своя «Отмена» выпускает, чужая — объясняет.

        Сюда же приходят кнопки меню, нажатые посреди диалога: меню остаётся
        висеть в переписке, нажать его во время разбора чека — обычное дело, а
        состояние в FSM одно на пользователя, и вопрос про почту затёр бы
        недоразобранный чек.
        """
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, _ = target

        branch = self._pressed_branch(callback.data)
        if branch is None:
            await self.hint(chat_id=chat_id, state=state)
            return

        if await self._current_branch(state) != branch:
            # Состояние цело: кнопка либо от другой ветки, либо от диалога,
            # который давно закончился.
            await self.aiogram.send_message(chat_id, CANCEL_STALE_MESSAGE)
            return

        await self.finish(chat_id=chat_id, state=state)
        await self.aiogram.send_message(chat_id, CANCELLED_MESSAGE)
        await self.menu().show(chat_id=chat_id)

    async def hint(self, *, chat_id: int, state: FSMContext) -> None:
        """Объясняет, что идёт другой диалог, и показывает выход из него.

        Подсказка **не** становится живой клавиатурой шага и не гасит
        предыдущую: пользователь мог нажать кнопку меню посреди разбора чека, и
        отобрать у него за это «Готово» значило бы наказать за любопытство.
        Своя кнопка у подсказки при этом есть — иначе выход пришлось бы искать
        выше по переписке, там, где его уже не ищут.
        """
        branch = await self._current_branch(state)
        if branch is None:
            # Мастер создания таблицы: кнопки у него нет, и звать нажать
            # несуществующее хуже, чем назвать настоящий выход.
            await self.aiogram.send_message(chat_id, DIALOG_IN_PROGRESS_NO_EXIT_MESSAGE)
            return

        await self.aiogram.send_message(
            chat_id,
            DIALOG_IN_PROGRESS_MESSAGE,
            keyboard=self.aiogram.inline_keyboard_rows([cancel_row(branch)]),
        )

    async def _current_branch(self, state: FSMContext) -> str | None:
        """Ветка, диалог которой сейчас идёт, либо `None`."""
        current = await self.aiogram.get_state(state)
        if current is None:
            return None
        return _STATE_BRANCHES.get(current)

    @staticmethod
    def _pressed_branch(data: str | None) -> str | None:
        """Метка ветки из `callback_data` кнопки «Отмена».

        `None` означает, что нажали не её, а кнопку меню: обе приходят в один
        обработчик, и различить их можно только по префиксу.
        """
        prefix = f"{CommandName.CANCEL}:"
        if not data or not data.startswith(prefix):
            return None
        return data[len(prefix) :] or None
