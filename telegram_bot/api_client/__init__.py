"""Клиент api: транспорт → доменные клиенты → шлюз.

Единственный способ, которым бот добирается до данных. Ни `httpx`, ни путей
эндпоинтов за пределами этого пакета нет.
"""

from __future__ import annotations

from telegram_bot.api_client.catalog import CatalogClient
from telegram_bot.api_client.checks import ChecksClient, CommitItem, NewProductType
from telegram_bot.api_client.errors import (
    ApiConflictError,
    ApiError,
    ApiNotFoundError,
    ApiUnavailableError,
    ApiValidationError,
)
from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.notifications import NotificationsClient
from telegram_bot.api_client.records import RecordsClient
from telegram_bot.api_client.spreadsheets import SpreadsheetsClient
from telegram_bot.api_client.transfers import TransfersClient


class ApiGateway:
    """Единая точка входа к api для команд бота."""

    def __init__(self, base_url: str, *, timeout: float) -> None:
        self._http = ApiHttpClient(base_url, timeout=timeout)
        self.spreadsheets = SpreadsheetsClient(self._http)
        self.catalog = CatalogClient(self._http)
        self.records = RecordsClient(self._http)
        self.transfers = TransfersClient(self._http)
        self.checks = ChecksClient(self._http)
        self.notifications = NotificationsClient(self._http)

    async def aclose(self) -> None:
        """Закрывает соединение с api."""
        await self._http.aclose()


__all__ = [
    "ApiConflictError",
    "ApiError",
    "ApiGateway",
    "ApiNotFoundError",
    "ApiUnavailableError",
    "ApiValidationError",
    "CatalogClient",
    "ChecksClient",
    "CommitItem",
    "NewProductType",
    "NotificationsClient",
    "RecordsClient",
    "SpreadsheetsClient",
    "TransfersClient",
]
