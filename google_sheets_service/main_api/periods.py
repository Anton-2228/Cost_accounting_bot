"""Клиент периодов и дневных итогов."""

from __future__ import annotations

from google_sheets_service.main_api.dto import CategoryDailyTotal, Period
from google_sheets_service.main_api.http import ApiHttpClient


class PeriodsApiClient:
    """Учётные месяцы документа и статистика по ним."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_all(self, spreadsheet_id: int) -> list[Period]:
        """Все периоды документа по возрастанию даты начала."""
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/periods")
        return [Period.from_json(item) for item in items]

    async def statistics(self, spreadsheet_id: int, period_id: int) -> list[CategoryDailyTotal]:
        """Дневные итоги по категориям — основа листа статистики.

        Считает их api: суммы должны сходиться с реестром, а значит жить там же,
        где деньги. Сервис только раскладывает плоский список в таблицу.
        """
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/periods/{period_id}/statistics"
        )
        return [CategoryDailyTotal.from_json(item) for item in items]
