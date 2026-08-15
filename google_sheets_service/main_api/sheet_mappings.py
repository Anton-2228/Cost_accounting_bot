"""Клиент соответствий «адресат перерисовки → лист документа»."""

from __future__ import annotations

import httpx

from google_sheets_service.main_api.dto import SheetMapping
from google_sheets_service.main_api.http import ApiHttpClient


class SheetMappingsApiClient:
    """Где лежат листы документа.

    Это знание хранит api, а не сервис: своей базы у сервиса нет, и после
    перезапуска он иначе не знал бы, создан ли уже лист периода.
    """

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[SheetMapping]:
        """Все известные листы документа."""
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/sheet-mappings")
        return [SheetMapping.from_json(item) for item in items]

    async def upsert(
        self,
        spreadsheet_id: int,
        *,
        target: str,
        google_sheet_id: int,
        title: str,
        period_id: int | None = None,
    ) -> SheetMapping:
        """Запоминает созданный лист.

        Вызывается **после** подтверждения от Google: наличие записи означает
        «лист существует», и запись вперёд факта сделала бы это утверждение
        ложным при первом же сбое.
        """
        body = await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/sheet-mappings",
            body={
                "target": target,
                "google_sheet_id": google_sheet_id,
                "title": title,
                "period_id": period_id,
            },
            expected=httpx.codes.OK,
        )
        return SheetMapping.from_json(body)
