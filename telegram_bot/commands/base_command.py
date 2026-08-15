"""Базовый класс команды."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiNotFoundError
from telegram_bot.api_client.models import Spreadsheet
from telegram_bot.errors import NO_TABLE_MESSAGE
from telegram_bot.notifications import NotificationCatchUp

if TYPE_CHECKING:
    from telegram_bot.commands.manager import Manager


class BaseCommand(ABC):
    """Общее для всех команд: доступ к api, обёртке aiogram и менеджеру."""

    def __init__(
        self,
        manager: Manager,
        api: ApiGateway,
        aiogram_wrapper: AiogramWrapper,
        catch_up: NotificationCatchUp,
    ) -> None:
        self.manager = manager
        self.api = api
        self.aiogram = aiogram_wrapper
        self.catch_up = catch_up

    @abstractmethod
    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Выполняет команду."""

    @staticmethod
    def user_id(message: Message) -> int:
        """Идентификатор автора сообщения.

        Везде именно `from_user`, а не `chat`: в группе это разные числа, и
        старая версия из-за расхождения искала таблицу по id чата в одной
        команде и по id пользователя во всех остальных.
        """
        if message.from_user is None:
            raise ValueError("Сообщение без автора")
        return message.from_user.id

    @staticmethod
    def text_of(message: Message) -> str | None:
        """Текст сообщения или `None`, если это не текст.

        Проверка обязательна на каждом шаге диалога: фотография или стикер в
        ожидании ответа давали в старой версии `TypeError` мимо всех
        обработчиков, и пользователь оставался в состоянии без единого слова в
        ответ.
        """
        return message.text

    async def spreadsheet(self, message: Message) -> Spreadsheet | None:
        """Таблица пользователя либо `None` с уже отправленной подсказкой.

        Ловится только 404 по ресурсу `spreadsheet`: старая версия отвечала
        «Сначала создайте таблицу» на любой 404, включая «нет такой операции».

        Здесь же — единственная точка дочитки уведомлений: это ровно тот
        момент, когда бот и знает документ, и разговаривает с его владельцем.
        """
        try:
            spreadsheet = await self.api.spreadsheets.by_telegram_id(self.user_id(message))
        except ApiNotFoundError as error:
            if error.resource not in {"spreadsheet", "user"}:
                raise
            await self.aiogram.answer_message(message, NO_TABLE_MESSAGE)
            return None

        await self.catch_up.deliver(spreadsheet.id, message.chat.id)
        return spreadsheet
