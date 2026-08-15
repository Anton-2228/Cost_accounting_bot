"""Команда `/cancel`: выход из любого диалога."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.resources.messages import CANCELLED_MESSAGE, NOTHING_TO_CANCEL_MESSAGE


class CancelCommand(BaseCommand):
    """Снимает состояние и стирает промежуточные данные.

    Зарегистрирована как настоящая команда для **всех** состояний. В старой
    версии `/cancel` был объявлен в меню Telegram, но существовал лишь как
    сравнение строки внутри разбора чека: вне тех состояний он давал «Не
    понимаю о чем речь», а форма `/cancel@ИмяБота` не срабатывала никогда.

    Отсюда же следует, что ни один диалог не может стать ловушкой: выход есть
    всегда и он один.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Прерывает диалог, если он идёт."""
        current = await self.aiogram.get_state(state)
        if current is None:
            await self.aiogram.answer_message(message, NOTHING_TO_CANCEL_MESSAGE)
            return

        await self.aiogram.clear_state(state)
        await self.aiogram.answer_message(message, CANCELLED_MESSAGE)
