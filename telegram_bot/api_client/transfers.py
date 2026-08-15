"""Клиент переводов между счетами."""

from __future__ import annotations

from decimal import Decimal

from telegram_bot import constants
from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import Transfer


class TransfersClient:
    """Добавление и удаление переводов.

    Удаление в старой версии отсутствовало вовсе: ошибочный перевод
    приходилось гасить встречным, и в реестре оставались две лишние строки.
    """

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def create(
        self,
        spreadsheet_id: int,
        *,
        from_source_id: int,
        to_source_id: int,
        amount: Decimal,
        notes: str,
    ) -> Transfer:
        """Записывает перевод. Сумма строго положительна: направление задают счета."""
        data = await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/transfers",
            body={
                "from_source_id": from_source_id,
                "to_source_id": to_source_id,
                "amount": str(amount),
                "notes": notes,
            },
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
        return Transfer.model_validate(data)

    async def delete_last(self, spreadsheet_id: int) -> Transfer:
        """Удаляет последний перевод текущего периода и возвращает его."""
        data = await self._http.delete_data(
            f"/spreadsheets/{spreadsheet_id}/transfers/last",
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
        return Transfer.model_validate(data)

    async def delete(self, spreadsheet_id: int, transfer_id: int) -> Transfer:
        """Удаляет перевод по идентификатору и возвращает его."""
        data = await self._http.delete_data(
            f"/spreadsheets/{spreadsheet_id}/transfers/{transfer_id}",
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
        return Transfer.model_validate(data)
