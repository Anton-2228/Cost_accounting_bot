"""Команда `/menu`: экран управления таблицей."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.enums import CommandName
from telegram_bot.i18n import t

#: `callback_data` кнопки «Назад» с экрана настроек: меню рисуется на месте того
#: же сообщения.
OPEN_DATA = f"{CommandName.MENU}:open"


#: Кнопки экрана: надпись и `callback_data`. Префикс `callback_data` совпадает с
#: ключом команды, которая кнопку обслуживает, — по нему нажатие и находит
#: обработчик. Тот же приём, что у кнопки настроек, и второй таблицы
#: соответствий из-за него не появляется.
#:
#: Порядок значим: `AiogramWrapper.inline_keyboard` кладёт по кнопке в ряд, и
#: список читается сверху вниз ровно так, как выглядит на экране.
def menu_buttons() -> tuple[tuple[str, str], ...]:
    """Кнопки экрана на языке обращения."""
    return (
        (t("buttons.menu.table"), f"{CommandName.TABLE}:show"),
        (t("buttons.menu.sync"), f"{CommandName.TABLE_SYNC}:run"),
        (t("buttons.menu.email"), f"{CommandName.TABLE_EMAIL}:ask"),
        (t("buttons.menu.unlink"), f"{CommandName.TABLE_UNLINK}:ask"),
        (t("buttons.menu.settings"), f"{CommandName.SETTINGS}:open"),
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

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """«Назад» с экрана настроек: меню на месте того же сообщения.

        Проверка та же, что у `/menu`, только отказ пишется на месте экрана:
        кнопка живёт в переписке дольше таблицы, и настройки, открытые до
        отвязки, не должны вернуть меню, где не работает ни одна кнопка.
        Дорисовка меню по `TABLE_READY` выключена — меню и так рисуется здесь,
        и без флага пришло бы дважды.
        """
        target = await self.callback_target(callback)
        if target is None or callback.message is None:
            return
        chat_id, telegram_id = target
        message_id = callback.message.message_id

        spreadsheet = await self.find_spreadsheet(
            user_id=telegram_id, chat_id=chat_id, menu_on_ready=False
        )
        refusal = self.refusal(spreadsheet)
        if refusal is not None:
            await self.show_screen(
                chat_id=chat_id, text=refusal, keyboard=None, message_id=message_id
            )
            return
        await self.show(chat_id=chat_id, message_id=message_id)

    async def show(self, *, chat_id: int, message_id: int | None = None) -> None:
        """Рисует экран в произвольном чате.

        Отдельный метод, а не только `execute`: меню показывается ещё из
        нескольких мест, где сообщения пользователя нет вовсе, — конца мастера
        создания таблицы, нажатия кнопки «Создать таблицу», «Отмены». Туда меню
        приходит новым сообщением; `message_id` передаёт только «Назад» с
        экрана настроек.
        """
        await self.show_screen(
            chat_id=chat_id,
            text=t("text.menu"),
            keyboard=self.aiogram.inline_keyboard(menu_buttons()),
            message_id=message_id,
        )
