"""Команда `/add`: добавление операции."""

from __future__ import annotations

from typing import Any

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.formatting import RecordFormatter
from telegram_bot.parsers import ParseError, RecordParser


class RecordAddCommand(BaseCommand):
    """`[день] валюта сумма категория [пометка...]` одной строкой.

    Валюта обязательна: подставить её больше неоткуда, а умолчание молча
    приписывало бы валюту той трате, где пользователь про неё забыл.

    Знак суммы не спрашивается и не принимается: расход это или доход,
    определяет вид категории. Так пользователь не может ошибиться знаком, а
    api — получить перевёрнутую операцию.

    День необязателен: без него дату ставит api по часовому поясу документа.
    Названный день обязан лежать в текущем периоде — правило «закрытый период
    не меняется» этим не нарушается, задним числом можно поправить только
    сегодняшний месяц.

    Границы периода едут в api только тогда, когда день действительно прислан:
    `/add` — самая частая команда бота, и лишний круг по сети на каждой трате
    ради необязательного аргумента ничего бы не добавил.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Разбирает строку и записывает операцию."""
        command: CommandObject | None = kwargs.get("command")
        raw_args = command.args if command else None

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        categories = await self.api.catalog.categories(spreadsheet.id)
        period = (
            await self.api.periods.current(spreadsheet.id)
            if RecordParser.starts_with_day(raw_args)
            else None
        )

        try:
            parsed = RecordParser.parse(
                raw_args,
                categories=categories,
                period=period,
            )
        except ParseError as error:
            await self.aiogram.answer_message(message, error.message)
            return

        # Период мог смениться между чтением границ и записью. Тогда api ответит
        # 422 `day_outside_period`, и его напечатает общий перехват в
        # `CommandManager`: перерисовывать здесь нечего, диалога у `/add` нет.
        record = await self.api.records.create(
            spreadsheet.id,
            category_id=parsed.category_id,
            amount=parsed.amount,
            currency=parsed.currency,
            notes=parsed.notes,
            added_at=parsed.added_at,
        )
        await self.aiogram.answer_message(message, RecordFormatter.saved(parsed, record))
