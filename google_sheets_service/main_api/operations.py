"""Клиент содержимого реестра: операции и переводы."""

from __future__ import annotations

from google_sheets_service.main_api.dto import Record, Transfer
from google_sheets_service.main_api.http import ApiHttpClient


class OperationsApiClient:
    """То, что печатается строками листа операций.

    Операции и переводы читаются раздельно, а в реестре идут вперемешку: перевод
    печатается такой же строкой, просто в колонке `Category` у него подпись
    «Перевод», а в `Source` — оба счёта.
    """

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_records(self, spreadsheet_id: int, period_id: int) -> list[Record]:
        """Операции периода."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/records",
            params={"period_id": period_id},
        )
        return [Record.from_json(item) for item in items]

    async def list_transfers(self, spreadsheet_id: int, period_id: int) -> list[Transfer]:
        """Переводы периода."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/transfers",
            params={"period_id": period_id},
        )
        return [Transfer.from_json(item) for item in items]
