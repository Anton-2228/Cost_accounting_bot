"""Клиент архива чеков."""

from __future__ import annotations

from google_sheets_service.main_api.dto import Check
from google_sheets_service.main_api.http import ApiHttpClient


class ChecksApiClient:
    """Разобранные чеки месяца — содержимое листа-архива.

    Своего периода у чека в базе нет: он приезжает из Mini App задолго до
    разбора, а месяц ему назначают операции, которые из него вышли. Поэтому
    выборка идёт фильтром по периоду, а не отдельным маршрутом: api считает
    принадлежность сам, и повторять этот вывод здесь незачем.
    """

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_by_period(self, spreadsheet_id: int, period_id: int) -> list[Check]:
        """Чеки, чьи операции попали в указанный период."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/checks",
            params={"period_id": period_id},
        )
        return [Check.from_json(item) for item in items]
