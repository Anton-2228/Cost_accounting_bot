"""Клиент основного api: транспорт, доменные клиенты и шлюз над ними."""

from __future__ import annotations

from checks_service.main_api.checks import ChecksApiClient, SavedCheck
from checks_service.main_api.http import ApiHttpClient
from checks_service.main_api.spreadsheets import Spreadsheet, SpreadsheetsApiClient


class ApiGateway:
    """Единая точка доступа к api поверх одного соединения.

    Доменные клиенты собираются здесь, а не в каждом потребителе: `httpx.
    AsyncClient` должен быть один на процесс — иначе пул соединений заводится
    на каждый домен заново.
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._http = ApiHttpClient(base_url, timeout=timeout)
        self.spreadsheets = SpreadsheetsApiClient(self._http)
        self.checks = ChecksApiClient(self._http)

    async def aclose(self) -> None:
        """Закрывает соединение с api."""
        await self._http.aclose()


__all__ = [
    "ApiGateway",
    "ApiHttpClient",
    "ChecksApiClient",
    "SavedCheck",
    "Spreadsheet",
    "SpreadsheetsApiClient",
]
