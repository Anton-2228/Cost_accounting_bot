"""Клиент обратного направления: правки листа едут в базу."""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from google_sheets_service.main_api.dto import ImportResult
from google_sheets_service.main_api.http import ApiHttpClient


class ImportsApiClient:
    """Отдаёт сырые строки листа в api.

    Сервис не разбирает содержимое и не судит о нём: он читает прямоугольник
    ячеек и передаёт как есть. Вся проверка — в `api/validation.py`, потому что
    там же живут правила уникальности имён и псевдонимов, о которых сервису
    знать неоткуда.
    """

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def import_categories(
        self,
        spreadsheet_id: int,
        rows: Sequence[Sequence[str]],
    ) -> ImportResult:
        """Применяет лист `Categories` целиком."""
        return await self._import(spreadsheet_id, "categories", rows)

    async def import_bills(
        self,
        spreadsheet_id: int,
        rows: Sequence[Sequence[str]],
    ) -> ImportResult:
        """Применяет лист `Bills` целиком."""
        return await self._import(spreadsheet_id, "bills", rows)

    async def _import(
        self,
        spreadsheet_id: int,
        resource: str,
        rows: Sequence[Sequence[str]],
    ) -> ImportResult:
        """Общая часть обоих импортов."""
        body = await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/import/{resource}",
            body={"rows": [list(row) for row in rows]},
            expected=httpx.codes.OK,
        )
        return ImportResult.from_json(body)
