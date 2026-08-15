"""Клиент основного api: транспорт, доменные клиенты и шлюз над ними."""

from __future__ import annotations

from google_sheets_service.main_api.http import ApiHttpClient
from google_sheets_service.main_api.imports import ImportsApiClient
from google_sheets_service.main_api.operations import OperationsApiClient
from google_sheets_service.main_api.periods import PeriodsApiClient
from google_sheets_service.main_api.sheet_mappings import SheetMappingsApiClient
from google_sheets_service.main_api.spreadsheets import SpreadsheetsApiClient
from google_sheets_service.main_api.tasks import TasksApiClient


class ApiGateway:
    """Единая точка доступа к api поверх одного соединения.

    Доменные клиенты собираются здесь, а не в каждом потребителе: движку удобнее
    получить один объект, а `httpx.AsyncClient` должен быть один на процесс —
    иначе пул соединений заводится на каждый домен заново.
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._http = ApiHttpClient(base_url, timeout=timeout)
        self.tasks = TasksApiClient(self._http)
        self.spreadsheets = SpreadsheetsApiClient(self._http)
        self.sheet_mappings = SheetMappingsApiClient(self._http)
        self.periods = PeriodsApiClient(self._http)
        self.operations = OperationsApiClient(self._http)
        self.imports = ImportsApiClient(self._http)

    async def aclose(self) -> None:
        """Закрывает соединение с api."""
        await self._http.aclose()


__all__ = [
    "ApiGateway",
    "ApiHttpClient",
    "ImportsApiClient",
    "OperationsApiClient",
    "PeriodsApiClient",
    "SheetMappingsApiClient",
    "SpreadsheetsApiClient",
    "TasksApiClient",
]
