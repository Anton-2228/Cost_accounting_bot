"""Клиент справочника категорий."""

from __future__ import annotations

from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import Category


class CatalogClient:
    """Чтение справочника документа.

    Правит его пользователь только в Google-таблице, а бот вчитывает изменения
    через `/table_sync`. Отсюда следствие: справочник бот не кэширует —
    единственный источник истины по нему api, и любой кэш означал бы окно, в
    котором только что добавленная категория «ещё не существует».
    """

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def categories(self, spreadsheet_id: int, *, only_active: bool = True) -> list[Category]:
        """Категории документа."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/categories",
            params={"only_active": only_active},
        )
        return [Category.model_validate(item) for item in items]

