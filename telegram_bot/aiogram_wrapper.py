"""Узкая обёртка над aiogram: Bot, Router, Dispatcher и FSM."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.dispatcher.event.handler import CallbackType
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from telegram_bot.logging import get_logger

logger = get_logger(__name__)


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

    @staticmethod
    def inline_keyboard_rows(
        rows: Sequence[Sequence[tuple[str, str]]],
    ) -> InlineKeyboardMarkup:
        """То же, но с явной раскладкой по рядам.

        Отдельный метод, а не замена `inline_keyboard`: экраны меню и настроек
        читаются списком сверху вниз, и оборачивать каждую их кнопку в
        одноэлементный ряд значило бы утяжелить их описание ради одной ветки.

        Ряды понадобились разбору чека: там на одном блоке до четырёх кнопок, и
        столбец из четырёх строк подряд занимает пол-экрана телефона.
        """
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
                for row in rows
                if row
            ]
        )

    async def clear_keyboard(self, chat_id: int, message_id: int) -> None:
        """Снимает клавиатуру с ранее отправленного сообщения.

        Любой отказ Telegram здесь глушится, и это не перестраховка. Гашение
        сопровождает шаг, а не составляет его: оно идёт первым в `finish`, и
        выброшенное отсюда исключение оставило бы пользователя в состоянии
        только что законченного диалога — со снятой кнопкой, но без выхода.
        Стоимость обратной ошибки несравнима: не снятая клавиатура — лишняя
        кнопка в переписке, и нажатие на неё отсекается сверкой ветки.

        Отказов таких много и все штатные: сообщение устарело, удалено
        пользователем, разметки на нём уже нет, сеть моргнула. Ловится общий
        предок ответов Telegram, а не их перечисление, — но именно он, а не
        `Exception`: ошибка в самом боте обязана остаться видимой.
        """
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except TelegramAPIError as error:
            logger.debug("Клавиатура сообщения %s не снята: %s", message_id, error)

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
