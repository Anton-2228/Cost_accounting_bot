"""Команда `/del_trans`: удаление перевода."""

from __future__ import annotations

from typing import Any

from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.formatting import TransferFormatter


class TransferDeleteCommand(BaseCommand):
    """`/del_trans [id]` — без аргумента удаляет последний перевод периода.

    В старой версии удаления перевода не существовало вовсе: ошибку гасили
    встречным переводом, и в реестре навсегда оставались две лишние строки, а
    в статистике — движение, которого не было.
    """

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Удаляет перевод по id или последний."""
        command: CommandObject | None = kwargs.get("command")
        raw = (command.args or "").strip() if command else ""

        transfer_id: int | None = None
        if raw:
            try:
                transfer_id = int(raw.split()[0])
            except ValueError:
                await self.aiogram.answer_message(
                    message, f"«{raw}» не похоже на id. Нужно так: /del_trans 42"
                )
                return

        spreadsheet = await self.spreadsheet(message)
        if spreadsheet is None:
            return

        transfer = (
            await self.api.transfers.delete(spreadsheet.id, transfer_id)
            if transfer_id is not None
            else await self.api.transfers.delete_last(spreadsheet.id)
        )

        sources = await self.api.catalog.sources(spreadsheet.id, only_active=False)
        await self.aiogram.answer_message(
            message, TransferFormatter.deleted(transfer, sources=sources)
        )
