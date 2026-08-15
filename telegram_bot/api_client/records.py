"""Клиент операций."""

from __future__ import annotations

from decimal import Decimal

from telegram_bot import constants
from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import Record


class RecordsClient:
    """Добавление и удаление операций."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def create(
        self,
        spreadsheet_id: int,
        *,
        category_id: int,
        source_id: int,
        amount: Decimal,
        notes: str,
    ) -> Record:
        """Записывает операцию.

        Сумма уходит **без знака**: расход это или доход, определяет вид
        категории. Минус от пользователя не может перевернуть операцию.
        """
        data = await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/records",
            body={
                "category_id": category_id,
                "source_id": source_id,
                "amount": str(amount),
                "notes": notes,
            },
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
        return Record.model_validate(data)

    async def delete_last(self, spreadsheet_id: int) -> Record:
        """Удаляет последнюю операцию текущего периода и возвращает её."""
        data = await self._http.delete_data(
            f"/spreadsheets/{spreadsheet_id}/records/last",
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
        return Record.model_validate(data)

    async def delete(self, spreadsheet_id: int, record_id: int) -> Record:
        """Удаляет операцию по идентификатору и возвращает её."""
        data = await self._http.delete_data(
            f"/spreadsheets/{spreadsheet_id}/records/{record_id}",
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
        return Record.model_validate(data)
