"""Команда `/menu`: экран управления таблицей."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.enums import CommandName
from telegram_bot.resources.messages import MENU_MESSAGE

#: Кнопки экрана: надпись и `callback_data`. Префикс `callback_data` совпадает с
#: ключом команды, которая кнопку обслуживает, — по нему нажатие и находит
#: обработчик. Тот же приём, что у кнопки настроек, и второй таблицы
#: соответствий из-за него не появляется.
#:
#: Порядок значим: `AiogramWrapper.inline_keyboard` кладёт по кнопке в ряд, и
#: список читается сверху вниз ровно так, как выглядит на экране.
MENU_BUTTONS = (
    ("Получить таблицу", f"{CommandName.TABLE}:show"),
    ("Синхронизировать таблицу", f"{CommandName.TABLE_SYNC}:run"),
    ("Дать доступ к таблице", f"{CommandName.TABLE_EMAIL}:ask"),
    ("Отвязать таблицу от бота", f"{CommandName.TABLE_UNLINK}:ask"),
    ("Настройки", f"{CommandName.SETTINGS}:open"),
)


class MenuCommand(BaseCommand):
    """Рисует меню действий с таблицей.

    Меню — единственный вход в эти действия: команд `/table`, `/table_sync`,
    `/table_email`, `/table_unlink` и `/settings` больше нет. Поэтому кнопки
    перечислены здесь одним списком, а не собираются по командам: список — это
    и есть описание экрана, и увидеть его целиком нужно в одном месте.

    Сама команда не выполняет ни одного из действий и ничего о них не знает,
    кроме надписи и ключа: нажатие уходит `Manager`-у, а тот — той команде, чей
    ключ стоит в префиксе. Иначе меню стало бы вторым местом, где живёт логика
    каждой из пяти веток.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Показывает меню владельцу таблицы.

        Без таблицы меню бессмысленно: все его кнопки работают с документом.
        Проверка через `spreadsheet` — она же и отвечает «Сначала создайте
        таблицу», тем же текстом, что все остальные команды.
        """
        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return
        await self.show(chat_id=message.chat.id)

    async def show(self, *, chat_id: int) -> None:
        """Рисует экран в произвольном чате.

        Отдельный метод, а не только `execute`: меню показывается ещё из двух
        мест, где сообщения пользователя нет вовсе, — конца мастера создания
        таблицы и нажатия кнопки «Создать таблицу».
        """
        await self.aiogram.send_message(
            chat_id,
            MENU_MESSAGE,
            keyboard=self.aiogram.inline_keyboard(MENU_BUTTONS),
        )
