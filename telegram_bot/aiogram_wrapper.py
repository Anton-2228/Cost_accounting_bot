"""Узкая обёртка над aiogram: Bot, Router, Dispatcher и FSM."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.dispatcher.event.handler import CallbackType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message


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

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        keyboard: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = None,
    ) -> Message:
        """Отправляет сообщение в произвольный чат (рассылка, шаги разбора).

        Разбор чека пишет именно так, а не `message.answer`: половина его шагов
        приходит из нажатия кнопки, где `callback.message` принадлежит боту, а
        не пользователю.

        `parse_mode` задаётся на месте вызова, а не глобально: разметка нужна
        ровно спискам разбора чека, а остальные сообщения несут данные
        пользователя — названия категорий, пометки операций, — и включённый на
        всех HTML превратил бы любую угловую скобку в них в сломанное сообщение.
        """
        return await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=parse_mode,
        )

    # --- Кнопки ----------------------------------------------------------

    @staticmethod
    def inline_keyboard(buttons: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
        """Клавиатура из пар «надпись, `callback_data`», по кнопке в ряд."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=text, callback_data=data)] for text, data in buttons
            ]
        )

    async def answer_callback(self, callback: CallbackQuery, text: str | None = None) -> None:
        """Гасит «часики» на кнопке, при необходимости показав всплывающий текст.

        Отвечать обязательно даже когда сказать нечего: без этого кнопка у
        пользователя крутится до таймаута Telegram.
        """
        await callback.answer(text=text)

    # --- Регистрация обработчиков ----------------------------------------

    def register_message_handler(
        self,
        handler: CallbackType,
        *filters: CallbackType,
    ) -> None:
        """Регистрирует обработчик входящих сообщений."""
        self.router.message.register(handler, *filters)

    def register_callback_handler(
        self,
        handler: CallbackType,
        *filters: CallbackType,
    ) -> None:
        """Регистрирует обработчик нажатия кнопки."""
        self.router.callback_query.register(handler, *filters)
