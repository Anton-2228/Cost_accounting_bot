"""Клиент содержимого реестра: операции периода."""

from __future__ import annotations

from google_sheets_service.main_api.dto import Record
from google_sheets_service.main_api.http import ApiHttpClient


class OperationsApiClient:
    """То, что печатается строками листа операций."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_records(self, spreadsheet_id: int, period_id: int) -> list[Record]:
        """Операции периода."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/records",
            params={"period_id": period_id},
        )
        return [Record.from_json(item) for item in items]

