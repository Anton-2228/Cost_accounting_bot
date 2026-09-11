"""Команда `/settings`: экран настроек, свой для админа и для пользователя."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.access import AccessGuard
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands import language_picker
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.menu import OPEN_DATA as MENU_OPEN_DATA
from telegram_bot.i18n import t
from telegram_bot.notifications import NotificationCatchUp

#: `callback_data` админской кнопки экрана. Префикс тот же, что ключ команды,
#: которая её обслуживает: по нему кнопка и находит обработчик.
LLM_COSTS_DATA = "settings_llm:costs"


class SettingsCommand(BaseCommand):
    """Показывает настройки.

    Ветка общая: `requires_admin` не переопределяется, потому что кнопка
    «Настройки» есть в меню у всех. Разное у ролей — не доступность, а
    содержимое экрана: язык меняет каждый, а траты на модель видит только
    админ.

    Сама команда ничего не решает о правах: кнопка ведёт в отдельную команду, и
    именно та объявлена админской. Проверять роль дважды — здесь для показа и
    там для выполнения — значило бы завести две точки правды о ней; здесь роль
    спрашивается только чтобы выбрать текст и набор кнопок.
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
        """Кнопка «Настройки» в меню и «Назад» с выбора языка.

        Обе рисуют экран на месте нажатого сообщения: меню, настройки и выбор
        языка сменяют друг друга в одном сообщении.
        """
        target = await self.callback_target(callback)
        if target is None or callback.message is None:
            return
        chat_id, telegram_id = target
        await self.show(
            chat_id=chat_id,
            telegram_id=telegram_id,
            message_id=callback.message.message_id,
        )

    async def show(self, *, chat_id: int, telegram_id: int, message_id: int | None = None) -> None:
        """Рисует экран в произвольном чате.

        Отдельный метод, а не только `execute`: этим же экраном заканчиваются
        показ трат и выбор языка, где сообщения пользователя нет — последний
        шаг пришёл кнопкой, а возвращаться нужно туда же, откуда ушли. Туда
        экран приходит новым сообщением; `message_id` передают только переходы
        по экранам навигации.
        """
        buttons = [(t("buttons.settings.language"), language_picker.open_data())]
        if self._access.is_admin(telegram_id):
            text = t("text.settings_admin")
            buttons.append((t("buttons.settings.llm_costs"), LLM_COSTS_DATA))
        else:
            text = t("text.settings_user")
        buttons.append((t("buttons.back"), MENU_OPEN_DATA))
        await self.show_screen(
            chat_id=chat_id,
            text=text,
            keyboard=self.aiogram.inline_keyboard(buttons),
            message_id=message_id,
        )
