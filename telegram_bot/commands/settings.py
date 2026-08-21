"""Команда `/settings`: экран настроек, свой для админа и для пользователя."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.access import AccessGuard
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.resources.messages import SETTINGS_ADMIN_MESSAGE, SETTINGS_STUB_MESSAGE

#: Надпись и `callback_data` единственной кнопки экрана. Префикс тот же, что
#: ключ команды, которая её обслуживает: по нему кнопка и находит обработчик.
LLM_COSTS_BUTTON = ("Траты на LLM", "settings_llm:costs")


class SettingsCommand(BaseCommand):
    """Показывает настройки.

    Ветка общая: `requires_admin` не переопределяется, потому что кнопка
    «Настройки» есть в меню у всех. Разной у ролей будет не доступность, а
    содержимое экрана — у обычного пользователя здесь пока нечего менять.

    Сама команда ничего не решает о правах: кнопка ведёт в отдельную команду, и
    именно та объявлена админской. Проверять роль дважды — здесь для показа и
    там для выполнения — значило бы завести две точки правды о ней; здесь роль
    спрашивается только чтобы выбрать текст.
    """

    def __init__(
        self,
        manager: Manager,
        api: ApiGateway,
        aiogram_wrapper: AiogramWrapper,
        catch_up: NotificationCatchUp,
        access: AccessGuard,
    ) -> None:
        super().__init__(manager, api, aiogram_wrapper, catch_up)
        self._access = access

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Отправляет экран настроек."""
        await self.show(chat_id=message.chat.id, telegram_id=self.user_id(message))

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Настройки» в меню."""
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, telegram_id = target
        await self.show(chat_id=chat_id, telegram_id=telegram_id)

    async def show(self, *, chat_id: int, telegram_id: int) -> None:
        """Рисует экран в произвольном чате.

        Отдельный метод, а не только `execute`: этим же экраном заканчивается
        показ трат, где сообщения пользователя нет — последний шаг мог прийти
        как угодно, а возвращаться после отчёта нужно туда же, откуда ушли.
        """
        if not self._access.is_admin(telegram_id):
            await self.aiogram.send_message(chat_id, SETTINGS_STUB_MESSAGE)
            return

        await self.aiogram.send_message(
            chat_id,
            SETTINGS_ADMIN_MESSAGE,
            keyboard=self.aiogram.inline_keyboard([LLM_COSTS_BUTTON]),
        )
