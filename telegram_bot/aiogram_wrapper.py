"""Узкая обёртка над aiogram: Bot, Router, Dispatcher и FSM."""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.dispatcher.event.handler import CallbackType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import Message


class AiogramWrapper:
    """Единственное место, где бот касается aiogram напрямую.

    Команды через неё получают ровно то, что им нужно: отправить сообщение,
    прочитать и записать поле FSM, сменить состояние. Прямой работы с `Bot`
    в командах нет — иначе подменить её в тестах было бы нечем, а вызовы
    Telegram расползлись бы по всем файлам.
    """

    def __init__(self, bot: Bot, router: Router, dispatcher: Dispatcher) -> None:
        self.bot = bot
        self.router = router
        self.dispatcher = dispatcher

    # --- Состояние -------------------------------------------------------

    async def set_state(self, state_context: FSMContext, state: State | None) -> None:
        """Устанавливает новое FSM-состояние (`None` — снять состояние)."""
        await state_context.set_state(state)

    async def get_state(self, state_context: FSMContext) -> str | None:
        """Возвращает текущее FSM-состояние."""
        return await state_context.get_state()

    async def clear_state(self, state_context: FSMContext) -> None:
        """Снимает состояние и стирает промежуточные данные диалога."""
        await state_context.clear()

    async def set_state_data(
        self,
        state_context: FSMContext,
        field_name: str,
        value: Any,
    ) -> None:
        """Сохраняет одно поле в FSM-данных."""
        await state_context.update_data({field_name: value})

    async def get_state_data(
        self,
        state_context: FSMContext,
        field_name: str,
        default: object = None,
    ) -> object:
        """Читает одно поле из FSM-данных.

        Именно `get` с умолчанием, а не подписка: диалог могли начать до
        перезапуска, и отсутствие ключа — рабочий случай, а не повод уронить
        обработчик `KeyError`-ом, как это делала старая версия.
        """
        data = await state_context.get_data()
        return data.get(field_name, default)

    # --- Сообщения -------------------------------------------------------

    async def answer_message(self, message: Message, text: str) -> Message:
        """Отправляет новое сообщение в ответ на полученное."""
        return await message.answer(text=text)

    async def send_message(self, chat_id: int, text: str) -> Message:
        """Отправляет сообщение в произвольный чат (рассылка уведомлений)."""
        return await self.bot.send_message(chat_id=chat_id, text=text)

    # --- Регистрация обработчиков ----------------------------------------

    def register_message_handler(
        self,
        handler: CallbackType,
        *filters: CallbackType,
    ) -> None:
        """Регистрирует обработчик входящих сообщений."""
        self.router.message.register(handler, *filters)
