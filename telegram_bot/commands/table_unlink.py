"""Команда `/table_unlink`: отвязать таблицу от бота."""

from __future__ import annotations

import unicodedata
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.cancel import BRANCH_UNLINK, cancel_row
from telegram_bot.enums import FsmDataKeys
from telegram_bot.i18n import t
from telegram_bot.states import States


class TableUnlinkCommand(BaseCommand):
    """Отвязывает таблицу от бота после явного подтверждения.

    Вопрос задаёт кнопка меню, отвечает пользователь фразой подтверждения:
    `handle_callback` ставит состояние, `execute` регистрируется единственно
    под ним и разбирает ответ. Фраза — на языке пользователя, и набрать её
    случайно нельзя: в этом и смысл.

    Сам Google-документ остаётся у владельца: бот отвязывает только то, чем
    владеет api. Об этом сказано в вопросе — иначе подтверждение давалось бы
    вслепую.
    """

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Отвязать таблицу от бота»: спрашивает подтверждение.

        Показанная фраза запоминается в FSM: язык может смениться между
        вопросом и ответом, и человек, набравший ровно то, что ему показали,
        не должен получить отказ.
        """
        target = await self.callback_target(callback)
        if target is None:
            return
        chat_id, _ = target

        phrase = t("table_unlink.phrase")
        await self.aiogram.set_state(state, States.CONFIRM_UNLINK_TABLE)
        await self.aiogram.set_state_data(state, FsmDataKeys.UNLINK_PHRASE, phrase)
        await self.ask(
            chat_id=chat_id,
            state=state,
            text=t("text.ask_unlink_confirm", word=phrase),
            rows=[cancel_row(BRANCH_UNLINK)],
        )

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Ответ на вопрос: фраза подтверждения отвязывает таблицу."""
        chat_id = message.chat.id
        text = self.text_of(message)
        shown = await self.aiogram.get_state_data(state, FsmDataKeys.UNLINK_PHRASE)
        # Диалог мог начаться до того, как фраза стала храниться: тогда
        # сверяем с фразой на текущем языке.
        phrase = shown if isinstance(shown, str) else t("table_unlink.phrase")
        if text is None or not _same_phrase(text, phrase):
            # Состояние снимается обязательно. Старая версия отвечала «удаление
            # отменено», но состояние оставляла, и следующее сообщение
            # пользователя снова трактовалось как подтверждение.
            await self.finish(chat_id=chat_id, state=state)
            await self.aiogram.answer_message(message, t("text.unlink_cancelled"))
            return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            await self.finish(chat_id=chat_id, state=state)
            return

        await self.api.spreadsheets.delete(spreadsheet.id)
        await self.finish(chat_id=chat_id, state=state)
        await self.aiogram.answer_message(message, t("text.table_unlinked"))


def _same_phrase(typed: str, expected: str) -> bool:
    """Совпадает ли набранное с фразой подтверждения.

    Сравнение после NFC и `casefold`: одна и та же буква хинди или французского
    приходит с клавиатуры то составной, то готовой, а регистр на телефоне
    зависит от автозамены. Лишние пробелы между словами тоже не в счёт — отказ
    из-за двойного пробела был бы отказом ни за что. Сама фраза при этом
    должна быть набрана целиком.
    """
    return _normalize(typed) == _normalize(expected)


def _normalize(value: str) -> str:
    """Фраза в виде для сравнения."""
    return unicodedata.normalize("NFC", " ".join(value.split())).casefold()
