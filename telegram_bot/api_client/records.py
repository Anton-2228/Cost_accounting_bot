"""Клиент операций."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from telegram_bot import constants
from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import Currency, Record


class RecordsClient:
    """Операции текущего периода, добавление и удаление."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def current(self, spreadsheet_id: int) -> list[Record]:
        """Живые операции текущего периода.

        Нужны `/del`: показать операцию до удаления, а не после.
        """
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/records")
        return [Record.model_validate(item) for item in items]

    async def create(
        self,
        spreadsheet_id: int,
        *,
        category_id: int,
        amount: Decimal,
        currency: Currency,
        notes: str,
        added_at: date | None = None,
    ) -> Record:
        """Записывает операцию.

        Сумма уходит **без знака**: расход это или доход, определяет вид
        категории. Минус от пользователя не может перевернуть операцию.

        `added_at` — день, которым датировать операцию; пусто значит
        «сегодняшний день документа», его подставит api.
        """
        data = await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/records",
            body={
                "category_id": category_id,
                "amount": str(amount),
                "currency": currency.value,
                "notes": notes,
                "added_at": added_at.isoformat() if added_at is not None else None,
            },
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
