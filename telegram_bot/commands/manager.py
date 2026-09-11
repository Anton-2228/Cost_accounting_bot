"""Диспетчер команд и единственная граница ошибок бота."""

from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from telegram_bot.access import ACCESS_DENIED_MESSAGE, AccessGuard
from telegram_bot.aiogram_wrapper import AiogramWrapper
from telegram_bot.api_client.errors import ApiError
from telegram_bot.commands.base_command import BaseCommand
from telegram_bot.errors import ApiErrorPresenter
from telegram_bot.i18n import Language, language_scope, t
from telegram_bot.i18n import language as i18n_language
from telegram_bot.languages import LanguageResolver
from telegram_bot.logging import get_logger

logger = get_logger(__name__)


class Manager:
    """Находит команду по ключу, проверяет доступ и роль, ловит всё, что упало.

    Право на админское действие объявляет сама команда (`requires_admin`), а
    проверяется оно здесь — там же, где доступ, и на обоих входах сразу. Иначе
    каждая следующая админская ветка помнила бы о проверке вручную, и первая
    забытая открыла бы её всем.

    Здесь же, один раз на входе, выбирается язык обращения: команда и всё, что
    она печатает, работают внутри `language_scope`. Посторонний получает отказ
    по-английски и до api не доходит — язык знает только api, а посторонних к
    нему не пускают вовсе.

    Граница ошибок здесь **одна и всеобъемлющая**. В старой версии ловились
    только ошибки api, а `ValueError`, `KeyError` и `TypeError` уходили в
    aiogram: пользователь не получал вообще ничего, а по логам это выглядело
    как «команда сработала». Отсюда правило: любое исключение обязано стать
    сообщением пользователю и записью в журнале.
    """

    def __init__(
        self,
        access: AccessGuard,
        aiogram_wrapper: AiogramWrapper,
        languages: LanguageResolver,
    ) -> None:
        self._access = access
        self._aiogram = aiogram_wrapper
        self._languages = languages
        self._commands: dict[str, BaseCommand] = {}

    def register(self, commands: dict[str, BaseCommand]) -> None:
        """Заполняет реестр команд."""
        self._commands.update(commands)

    def get(self, name: str) -> BaseCommand:
        """Команда по ключу; отсутствие — ошибка сборки, а не ввода."""
        command = self._commands.get(name)
        if command is None:
            raise KeyError(f"Команда «{name}» не зарегистрирована")
        return command

    async def launch(
        self,
        name: str,
        message: Message,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """Выполняет команду, превращая любую ошибку в ответ пользователю."""
        telegram_id = message.from_user.id if message.from_user else None
        if telegram_id is None or not self._access.is_allowed(telegram_id):
            await self._aiogram.answer_message(message, ACCESS_DENIED_MESSAGE)
            return

        command = self.get(name)
        with language_scope(await self._language_of(telegram_id)):
            if command.requires_admin and not self._access.is_admin(telegram_id):
                await self._aiogram.answer_message(message, t("access.admin_only"))
                return

            try:
                await command.execute(message, state, **kwargs)
            except ApiError as error:
                logger.warning("Команда «%s» не удалась: %s", name, error)
                await self._answer_safely(message, ApiErrorPresenter.present(error))
            except Exception:
                logger.exception("Команда «%s» упала", name)
                await self._answer_safely(message, t("errors.unexpected"))

    async def launch_callback(
        self,
        name: str,
        callback: CallbackQuery,
        state: FSMContext,
        **kwargs: Any,
    ) -> None:
        """То же для нажатия кнопки.

        Отдельный вход, а не `launch` по `callback.message`: у того сообщения
        автор — бот, и проверка доступа по нему отказала бы законному
        пользователю, а поиск документа ушёл бы не туда.

        Роль проверяется и здесь. Одной проверки в `launch` не хватило бы:
        кнопка живёт в переписке дольше команды, её `callback_data` видна
        клиенту, и админская ветка, защищённая только со стороны команды,
        осталась бы доступна нажатием.
        """
        telegram_id = callback.from_user.id if callback.from_user else None
        if telegram_id is None or not self._access.is_allowed(telegram_id):
            await self._aiogram.answer_callback(callback, ACCESS_DENIED_MESSAGE)
            return

        command = self.get(name)
        with language_scope(await self._language_of(telegram_id)):
            if command.requires_admin and not self._access.is_admin(telegram_id):
                await self._aiogram.answer_callback(callback, t("access.admin_only"))
                return

            try:
                await command.handle_callback(callback, state, **kwargs)
            except ApiError as error:
                logger.warning("Кнопка команды «%s» не сработала: %s", name, error)
                await self._answer_callback_safely(callback, ApiErrorPresenter.present(error))
            except Exception:
                logger.exception("Кнопка команды «%s» упала", name)
                await self._answer_callback_safely(callback, t("errors.unexpected"))

    async def reply_unknown(self, message: Message) -> None:
        """Ответ на всё, что не подошло ни одному обработчику.

        Через `Manager`, а не прямой отправкой: ответ обязан быть на языке
        пользователя, а язык выбирается здесь. Посторонний получает тот же
        отказ, что и на любую команду.
        """
        telegram_id = message.from_user.id if message.from_user else None
        if telegram_id is None or not self._access.is_allowed(telegram_id):
            await self._answer_safely(message, ACCESS_DENIED_MESSAGE)
            return
        with language_scope(await self._language_of(telegram_id)):
            await self._answer_safely(message, t("text.unknown"))

    async def _language_of(self, telegram_id: int) -> Language:
        """Язык пользователя; сбой — язык по умолчанию, а не упавшее обращение.

        Настоящий источник и сам не бросает, но граница ошибок одна на весь бот:
        то, что проскочило бы отсюда, осталось бы вовсе без ответа.
        """
        try:
            return await self._languages.resolve(telegram_id)
        except Exception:
            logger.exception("Язык пользователя %s не определён", telegram_id)
            return i18n_language.DEFAULT_LANGUAGE

    async def _answer_safely(self, message: Message, text: str) -> None:
        """Отвечает пользователю, не давая упасть самому обработчику ошибки.

        Telegram может отказать в отправке (бот заблокирован, чат удалён). Это
        не повод потерять запись об исходной ошибке в журнале.
        """
        try:
            await self._aiogram.answer_message(message, text)
        except Exception:
            logger.exception("Не удалось отправить сообщение об ошибке")

    async def _answer_callback_safely(self, callback: CallbackQuery, text: str) -> None:
        """Отвечает на нажатие кнопки, не давая упасть обработчику ошибки.

        Сначала гасим «часики»: без ответа на callback кнопка у пользователя
        крутится до таймаута Telegram, даже если сообщение об ошибке дошло.
        """
        try:
            await self._aiogram.answer_callback(callback)
            if callback.message is not None:
                await self._aiogram.send_message(callback.message.chat.id, text)
        except Exception:
            logger.exception("Не удалось отправить сообщение об ошибке")
