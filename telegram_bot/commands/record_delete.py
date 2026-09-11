"""Команда `/del`: удаление операции после подтверждения."""

from __future__ import annotations

from typing import Any

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.api_client.models import Record
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.cancel import BRANCH_DELETE, cancel_row
from telegram_bot.enums import FsmDataKeys
from telegram_bot.formatting import RecordFormatter
from telegram_bot.i18n import t
from telegram_bot.states import States


class RecordDeleteCommand(BaseCommand):
    """`/del [id]` — без аргумента удаляет последнюю операцию периода.

    Идентификатор пользователь берёт из ответа на `/add`: списка
    операций в боте нет, отчётная поверхность — сама таблица.

    Удаляет не сразу: сначала показывает операцию целиком и просит набрать её
    id. Без аргумента пользователь не знает, какая операция сейчас последняя —
    её могли добавить разбором чека или с другого устройства, — а с аргументом
    легко промахнуться цифрой. Набранный id закрывает оба случая: человек видит,
    что удаляет, и подтверждает именно это.

    Команда и ответ на вопрос приходят сюда же, и `execute` различает их по
    состоянию — как у `TableUnlinkCommand`.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Спрашивает подтверждение либо разбирает ответ на него."""
        if await self.aiogram.get_state(state) == States.CONFIRM_DELETE_RECORD.state:
            await self._confirm(message, state)
            return
        await self._ask(message, state, kwargs.get("command"))

    async def _ask(
        self,
        message: Message,
        state: FSMContext,
        command: CommandObject | None,
    ) -> None:
        """Находит операцию и показывает её вместе с вопросом.

        Операция ищется среди операций текущего периода и только там: из
        закрытого периода api удалять не даёт, и показывать такую операцию для
        подтверждения значило бы спросить о том, чего всё равно не сделать.
        """
        raw = (command.args or "").strip() if command else ""

        record_id: int | None = None
        if raw:
            try:
                record_id = int(raw.split()[0])
            except ValueError:
                await self.aiogram.answer_message(message, t("record_delete.bad_id", raw=raw))
                return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        record = _pick(await self.api.records.current(spreadsheet.id), record_id)
        if record is None:
            await self.aiogram.answer_message(
                message,
                t("record_delete.empty")
                if record_id is None
                else t("record_delete.not_in_period", id=record_id),
            )
            return

        categories = await self.api.catalog.categories(spreadsheet.id, only_active=False)
        await self.aiogram.set_state(state, States.CONFIRM_DELETE_RECORD)
        await self.aiogram.set_state_data(state, FsmDataKeys.DELETE_RECORD_ID, record.id)
        await self.ask(
            chat_id=message.chat.id,
            state=state,
            text=t(
                "text.ask_record_delete",
                card=RecordFormatter.card(record, categories=categories),
                id=record.id,
            ),
            rows=[cancel_row(BRANCH_DELETE)],
        )

    async def _confirm(self, message: Message, state: FSMContext) -> None:
        """Ответ на вопрос: набранный id показанной операции удаляет её."""
        chat_id = message.chat.id
        text = self.text_of(message)
        shown = await self.aiogram.get_state_data(state, FsmDataKeys.DELETE_RECORD_ID)
        if not isinstance(shown, int) or text is None or text.strip() != str(shown):
            await self.finish(chat_id=chat_id, state=state)
            await self.aiogram.answer_message(message, t("text.record_delete_cancelled"))
            return

        # Состояние снимается до обращения к api, а не после. Операцию могли
        # удалить в другом месте (404), а период — закрыть, пока человек
        # отвечал (422): ошибку `Manager` покажет сам, но состояние после неё
        # осталось бы висеть, и следующее сообщение снова читалось бы как id.
        await self.finish(chat_id=chat_id, state=state)

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        # Удаляется показанная операция, а не последняя на момент ответа: между
        # вопросом и ответом могла появиться новая, и подтверждение досталось
        # бы ей.
        record = await self.api.records.delete(spreadsheet.id, shown)
        categories = await self.api.catalog.categories(spreadsheet.id, only_active=False)
        await self.aiogram.answer_message(
            message,
            RecordFormatter.deleted(record, categories=categories),
        )


def _pick(records: list[Record], record_id: int | None) -> Record | None:
    """Операция с этим id, а без id — последняя; `None`, если такой нет.

    Последняя — с наибольшим id, как и у api: на порядок списка в ответе
    вывод не опирается.
    """
    if record_id is None:
        return max(records, key=lambda item: item.id, default=None)
    return next((item for item in records if item.id == record_id), None)
