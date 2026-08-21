"""Клиент учётных периодов."""

from __future__ import annotations

from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import Period


class PeriodsClient:
    """Чтение периодов документа."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_for_spreadsheet(self, spreadsheet_id: int) -> list[Period]:
        """Все периоды документа по возрастанию даты начала.

        Нужны там, где траты раскладываются по учётным месяцам: период — строка
        в базе, а не арифметика по `reset_day`, и вычислять границы на своей
        стороне значило бы завести вторую версию календаря, расходящуюся с
        первой на каждом пропущенном ролловере.
        """
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/periods")
        return [Period.model_validate(item) for item in items]
