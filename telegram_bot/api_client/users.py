"""Клиент раздела «пользователь»: язык интерфейса."""

from __future__ import annotations

from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.i18n.language import Language


class UsersClient:
    """Чтение и смена языка пользователя."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def language(self, telegram_id: int) -> Language | None:
        """Язык пользователя; 404 по ресурсу `user`, если его нет в базе.

        `None` — api знает язык, которого нет у бота (бот отстал на выкладку):
        говорить с таким пользователем придётся на языке по умолчанию.
        """
        data = await self._http.get_data(f"/users/{telegram_id}")
        return Language.from_code(str(data.get("language", "")))

    async def set_language(self, telegram_id: int, language: Language) -> Language | None:
        """Записывает язык; незнакомого пользователя api заводит сам."""
        data = await self._http.put_data(
            f"/users/{telegram_id}/language",
            body={"language": language.value},
        )
        return Language.from_code(str(data.get("language", "")))
