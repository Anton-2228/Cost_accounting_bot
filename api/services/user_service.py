"""Пользователь целиком: язык интерфейса."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.db.transaction import commit
from api.domain.user import User
from api.enums import Language
from api.exceptions.base import NotFoundError
from api.repositories.user_repository import UserRepository

logger = get_logger(__name__)


class UserService:
    """Чтение пользователя и смена его языка.

    Не наследует `BaseSpreadsheetService`: пользователь существует и без
    документа — язык выбирается на `/start` раньше, чем заведена таблица, — и
    требовать документ здесь значило бы запретить выбор языка тому, кто только
    пришёл.
    """

    def __init__(self, session: AsyncSession, users: UserRepository) -> None:
        self._session = session
        self._users = users

    async def get(self, telegram_id: int) -> User:
        """Пользователь по telegram_id или 404 по ресурсу `user`.

        404, а не пользователь с языком по умолчанию: api не выдумывает строк,
        которых нет. Отвечать умолчанием на незнакомого — забота того, кто
        спрашивает.
        """
        user = await self._users.get_by_telegram_id(telegram_id)
        if user is None:
            raise NotFoundError("user")
        return user

    async def set_language(self, telegram_id: int, language: Language) -> User:
        """Записывает язык; незнакомого пользователя заводит."""
        user = await self._users.set_language(telegram_id, language)
        await commit(self._session)
        logger.info("Пользователь %s выбрал язык %s", telegram_id, language)
        return user
