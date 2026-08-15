"""Клиент документа: единственное, что сервису нужно знать о таблице."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from checks_service.main_api.http import ApiHttpClient


@dataclass(frozen=True)
class Spreadsheet:
    """Учётная таблица пользователя.

    Зеркало `api/responses/spreadsheets/spreadsheet_response.py`, урезанное до
    того, что здесь используется. Дублирование намеренно — как и в
    `google_sheets_service`: общего пакета схем нет, а импорт `api` затащил бы
    сюда SQLAlchemy.
    """

    id: int
    title: str

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Spreadsheet:
        """Собирает документ из ответа api."""
        return cls(id=int(body["id"]), title=str(body["title"]))


class SpreadsheetsApiClient:
    """Документ пользователя по его telegram_id."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def get_by_telegram(self, telegram_id: int) -> Spreadsheet | None:
        """Документ пользователя или `None`, если таблицы ещё нет.

        Отсутствие таблицы — рабочий случай, а не сбой: пользователь мог не
        пройти `/start`. Поэтому 404 превращается в `None`, а не в исключение.
        """
        body = await self._http.get_data(
            f"/spreadsheets/by-telegram/{telegram_id}",
            allow_404=True,
        )
        return None if body is None else Spreadsheet.from_json(body)
