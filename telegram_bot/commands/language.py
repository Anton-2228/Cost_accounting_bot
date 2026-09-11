"""Выбор языка: из настроек и на каждом `/start`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client import ApiGateway
from telegram_bot.commands import language_picker
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.commands.language_picker import (
    ACTION_OPEN,
    ACTION_PAGE,
    ACTION_SET,
    ORIGIN_SETTINGS,
    ORIGIN_START,
)
from telegram_bot.commands.manager import Manager
from telegram_bot.enums import CommandName
from telegram_bot.i18n import (
    SUPPORTED_LANGUAGES,
    Language,
    current_language,
    language_scope,
    t,
    t_in,
)
from telegram_bot.languages import LanguageStore
from telegram_bot.notifications import NotificationCatchUp

if TYPE_CHECKING:
    from telegram_bot.commands.settings import SettingsCommand
    from telegram_bot.commands.start import StartCommand


class LanguageCommand(BaseCommand):
    """Показывает выбор языка, листает его и записывает выбранное.

    Своя команда, а не ветка настроек: тот же выбор показывает `/start`, ещё до
    всяких настроек и таблиц. Откуда выбор открыт, едет в `callback_data`, и по
    нему после выбора бот продолжает там же — приветствием после `/start`,
    экраном настроек после настроек.

    Язык обращения здесь уже выставлен `Manager`-ом, поэтому отметка ✓ и
    подпись над выбором из настроек — на текущем языке пользователя. Подпись
    над выбором на `/start` — всегда английская: её читает и тот, кто ещё
    ничего не выбирал.
    """

    def __init__(
        self,
        manager: Manager,
        api: ApiGateway,
        aiogram_wrapper: AiogramWrapper,
        catch_up: NotificationCatchUp,
        languages: LanguageStore,
    ) -> None:
        super().__init__(manager, api, aiogram_wrapper, catch_up)
        self._languages = languages

    async def execute(self, message: Message, state: FSMContext, **kwargs: Any) -> None:
        """Входа командой у этой ветки нет.

        Не заглушка «на всякий случай»: сюда можно попасть только ошибкой
        сборки — регистрацией кнопочной команды как текстовой.
        """
        raise NotImplementedError("Выбор языка — только кнопки")

    async def show(self, *, chat_id: int, origin: str) -> None:
        """Присылает выбор языка новым сообщением на странице текущего языка."""
        current = current_language()
        text = (
            t_in(Language.EN, "language.choose_start")
            if origin == ORIGIN_START
            else t("language.choose")
        )
        await self.aiogram.send_message(
            chat_id,
            text,
            keyboard=self.aiogram.inline_keyboard_rows(
                language_picker.rows(
                    origin=origin,
                    page=language_picker.page_of(current),
                    current=current,
                )
            ),
        )

    async def handle_callback(
        self,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Кнопка «Язык» в настройках, листание страниц и выбор языка."""
        target = await self.callback_target(callback)
        if target is None or callback.message is None:
            return
        chat_id, telegram_id = target

        action = language_picker.parse(callback.data)
        if action is None:
            return
        if action.action == ACTION_OPEN:
            await self.show(chat_id=chat_id, origin=ORIGIN_SETTINGS)
            return

        message_id = callback.message.message_id
        if action.action == ACTION_PAGE and action.origin is not None:
            value = action.value or ""
            current = current_language()
            await self.aiogram.edit_keyboard(
                chat_id,
                message_id,
                self.aiogram.inline_keyboard_rows(
                    language_picker.rows(
                        origin=action.origin,
                        page=int(value) if value.isdigit() else 1,
                        current=current,
                    )
                ),
            )
            return
        if action.action == ACTION_SET:
            language = Language.from_code(action.value or "")
            if language is None or language not in SUPPORTED_LANGUAGES:
                return
            await self._choose(
                chat_id=chat_id,
                telegram_id=telegram_id,
                message_id=message_id,
                language=language,
                origin=action.origin,
            )

    async def _choose(
        self,
        *,
        chat_id: int,
        telegram_id: int,
        message_id: int,
        language: Language,
        origin: str | None,
    ) -> None:
        """Записывает язык и продолжает там, откуда пришли — уже на нём.

        Сообщение с выбором превращается в подтверждение без кнопок: живой
        выбор над приветствием звал бы выбирать снова. Не удалось переписать
        (сообщение удалено, устарело) — подтверждение приходит новым.
        """
        saved = await self._languages.change(telegram_id, language)
        with language_scope(saved):
            confirmation = t("language.changed")
            if not await self.aiogram.edit_text(chat_id, message_id, confirmation):
                await self.aiogram.send_message(chat_id, confirmation)
            if origin == ORIGIN_START:
                await self._start().greet(chat_id=chat_id, telegram_id=telegram_id)
            else:
                await self._settings().show(chat_id=chat_id, telegram_id=telegram_id)

    def _start(self) -> StartCommand:
        """Команда входа из реестра — тем же способом, что и меню."""
        return cast("StartCommand", self.manager.get(CommandName.START))

    def _settings(self) -> SettingsCommand:
        """Экран настроек из реестра."""
        return cast("SettingsCommand", self.manager.get(CommandName.SETTINGS))
