"""Язык каждого пользователя: api — источник, здесь — кэш процесса."""

from __future__ import annotations

from typing import Protocol

from telegram_bot.api_client import ApiGateway
from telegram_bot.api_client.errors import ApiError, ApiNotFoundError
from telegram_bot.i18n import Language
from telegram_bot.i18n import language as i18n_language
from telegram_bot.logging import get_logger

logger = get_logger(__name__)


class LanguageResolver(Protocol):
    """Узнаёт язык пользователя. Нужен `Manager` — на каждое обращение."""

    async def resolve(self, telegram_id: int) -> Language:
        """Язык пользователя; никогда не бросает."""
        ...


class LanguageStore(LanguageResolver, Protocol):
    """То же, плюс смена языка. Нужна команде выбора языка."""

    async def change(self, telegram_id: int, language: Language) -> Language:
        """Записывает язык и возвращает записанный."""
        ...


class UserLanguages:
    """Языки пользователей с кэшем в памяти процесса.

    Язык нужен на каждое обращение, а спрашивать его у api каждый раз значило
    бы удвоить число запросов ради значения, которое меняется раз в жизни
    пользователя. Кэш в памяти, а не в Redis: бот работает одним процессом, и
    язык меняет только он сам — через :meth:`change`, который кэш и обновляет.
    Список небольшой: к боту пускают только перечисленных в окружении.

    Незнакомый api пользователь говорит на языке по умолчанию, и это тоже
    кэшируется: иначе новичок, так и не выбравший язык, стоил бы запроса на
    каждое сообщение. Недоступность api — нет: сбой временный, и запомнить его
    значило бы говорить с человеком не на его языке до перезапуска бота.
    """

    def __init__(self, api: ApiGateway) -> None:
        self._api = api
        self._cache: dict[int, Language] = {}

    async def resolve(self, telegram_id: int) -> Language:
        """Язык пользователя; при любой неудаче — язык по умолчанию."""
        cached = self._cache.get(telegram_id)
        if cached is not None:
            return cached

        try:
            language = await self._api.users.language(telegram_id)
        except ApiNotFoundError as error:
            if error.resource != "user":
                logger.warning("Язык пользователя %s не прочитан: %s", telegram_id, error)
                return i18n_language.DEFAULT_LANGUAGE
            language = None
        except ApiError as error:
            logger.warning("Язык пользователя %s не прочитан: %s", telegram_id, error)
            return i18n_language.DEFAULT_LANGUAGE

        resolved = language or i18n_language.DEFAULT_LANGUAGE
        self._cache[telegram_id] = resolved
        return resolved

    async def change(self, telegram_id: int, language: Language) -> Language:
        """Записывает язык в api и в кэш.

        Кэш обновляется только после ответа api: язык, который не записался,
        не должен продолжать жить в боте, выдавая себя за выбранный.
        """
        saved = await self._api.users.set_language(telegram_id, language) or language
        self._cache[telegram_id] = saved
        return saved
