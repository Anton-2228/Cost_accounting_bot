"""Клиент пользователя: единственное, что сервису нужно знать о нём, — язык."""

from __future__ import annotations

from checks_service.main_api.http import ApiHttpClient


class UsersApiClient:
    """Язык пользователя по его telegram_id."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def language(self, telegram_id: int) -> str | None:
        """Код языка в нижнем регистре (`ru`, `en`, …) или `None`.

        `None` — пользователя api не знает: он ещё ни разу не выбирал язык и не
        заводил таблицу. Код приводится к нижнему регистру здесь: страница
        называет свои каталоги кодами ISO 639-1, а api хранит перечисление в
        верхнем.
        """
        body = await self._http.get_data(f"/users/{telegram_id}", allow_404=True)
        if body is None:
            return None
        return str(body.get("language", "")).lower() or None
