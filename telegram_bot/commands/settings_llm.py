"""Админская ветка настроек: траты на модель по одному пользователю."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiNotFoundError
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.cancel import BRANCH_LLM, cancel_row
from telegram_bot.commands.manager import Manager
from telegram_bot.commands.settings import SettingsCommand
from telegram_bot.formatting import LlmUsageFormatter, SpreadsheetUsage
from telegram_bot.notifications import NotificationCatchUp
from telegram_bot.resources.messages import (
    ASK_LLM_TELEGRAM_ID_MESSAGE,
    BAD_TELEGRAM_ID_MESSAGE,
)
from telegram_bot.states import States

USER_NOT_FOUND_TEMPLATE = "Пользователь {telegram_id} не найден. Пришлите другой id."


class SettingsLlmCostsCommand(BaseCommand):
    """Спрашивает telegram id и показывает траты на модель по этому человеку.

    `requires_admin` — единственное место, где право на эту ветку записано.
    `Manager` проверяет его и на нажатии кнопки, и на шаге диалога, поэтому
    добраться до отчёта в обход роли нельзя: ни живой кнопкой из чужой
    переписки, ни вводом id в состоянии, оставшемся с прежней роли.

    Считает бот, а не api. Траты раскладываются по учётным периодам, а границы
    периода — даты в часовом поясе **таблицы**, и собрать одно с другим можно,
    только зная сразу таблицы, их периоды и замеры.
    """

    requires_admin = True

    def __init__(
        self,
        manager: Manager,
        api: ApiGateway,
        aiogram_wrapper: AiogramWrapper,
        catch_up: NotificationCatchUp,
        settings: SettingsCommand,
    ) -> None:
        super().__init__(manager, api, aiogram_wrapper, catch_up)
        self._settings = settings

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Нажатие кнопки «Траты на LLM»: спрашивает, чьи именно."""
        target = await self.callback_target(callback)
        if target is None:
            # Сообщение старше суток Telegram к кнопке не прикладывает. Отвечать
            # некуда, а состояние без вопроса оставило бы админа гадать, чего от
            # него ждут.
            return
        chat_id, _ = target

        await self.aiogram.set_state(state, States.SETTINGS_ASK_TELEGRAM_ID)
        await self._ask(chat_id, state, ASK_LLM_TELEGRAM_ID_MESSAGE)

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Шаг ввода id: показывает отчёт и возвращает экран настроек.

        Ошибка ввода и неизвестный пользователь состояние не сбрасывают: админ
        ошибся в числе, а не передумал, и выкидывать его из диалога значило бы
        заставлять начинать с `/settings` из-за опечатки.
        """
        chat_id = message.chat.id
        text = self.text_of(message)
        telegram_id = None if text is None else self._parse_telegram_id(text)
        if telegram_id is None:
            await self._ask(chat_id, state, BAD_TELEGRAM_ID_MESSAGE)
            return

        try:
            items = await self._collect(telegram_id)
        except ApiNotFoundError as error:
            if error.resource != "user":
                raise
            await self._ask(
                chat_id,
                state,
                USER_NOT_FOUND_TEMPLATE.format(telegram_id=telegram_id),
            )
            return

        for block in LlmUsageFormatter.report(telegram_id, items):
            await self.aiogram.send_message(chat_id, block)

        await self.finish(chat_id=chat_id, state=state)
        await self._settings.show(chat_id=chat_id, telegram_id=self.user_id(message))

    async def _ask(self, chat_id: int, state: FSMContext, text: str) -> None:
        """Вопрос или отказ ввода — с кнопкой выхода из ветки.

        Кнопку несёт и отказ: админ ошибся в числе, а не передумал, и состояние
        поэтому остаётся, — но живая кнопка обязана переехать вниз вместе с
        последним сообщением, иначе выход остался бы висеть над отчётом.
        """
        await self.ask(chat_id=chat_id, state=state, text=text, rows=[cancel_row(BRANCH_LLM)])

    async def _collect(self, telegram_id: int) -> list[SpreadsheetUsage]:
        """Собирает по пользователю всё, из чего считается отчёт.

        Запросы последовательные, а не параллельные: таблиц у человека единицы,
        выигрыш во времени был бы незаметен, а очередь запросов к api осталась
        бы предсказуемой — отчёт запрашивает один админ вручную, и разгонять
        ради него веер обращений не за чем.
        """
        spreadsheets = await self.api.spreadsheets.list_by_telegram_id(telegram_id)
        items: list[SpreadsheetUsage] = []
        for spreadsheet in spreadsheets:
            items.append(
                SpreadsheetUsage(
                    spreadsheet=spreadsheet,
                    periods=await self.api.periods.list_for_spreadsheet(spreadsheet.id),
                    usages=await self.api.llm_usages.list_for_spreadsheet(spreadsheet.id),
                )
            )
        return items

    @staticmethod
    def _parse_telegram_id(raw: str) -> int | None:
        """Идентификатор Telegram из введённой строки или `None`.

        Отрицательные не принимаются намеренно: минус в этом числе означает чат
        (группу или канал), а траты считаются по человеку. Приняв его, бот
        ответил бы «не найден» вместо объяснения, что спрашивали другое.
        """
        candidate = raw.strip()
        if not candidate.isdigit():
            return None
        return int(candidate)
