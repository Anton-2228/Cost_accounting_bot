"""Асинхронная обёртка над Google Sheets API.

Официальный SDK синхронный, поэтому каждый вызов уходит в поток через
`anyio.to_thread.run_sync`. Клиент намеренно тонкий: он ничего не знает ни о
листах учёта, ни о перерисовке — только выполняет запросы и повторяет их при
восстановимых сбоях.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any

import anyio
import google_auth_httplib2
import httplib2
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from google_sheets_service.exceptions import GoogleApiError
from google_sheets_service.google.retry import RetryPolicy, to_dict
from google_sheets_service.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SheetProperties:
    """Метаданные одного листа документа."""

    sheet_id: int
    title: str
    row_count: int
    column_count: int
    #: Идентификаторы уже наложенных защит. Нужны, чтобы оформление можно было
    #: применить повторно: `addProtectedRange` не идемпотентен и на второй раз
    #: кладёт вторую защиту поверх первой.
    protected_range_ids: tuple[int, ...] = ()


class GoogleSheetsClient:
    """Обёртка над `spreadsheets` из `googleapiclient`."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        timeout_seconds: float = 20.0,
        retry: RetryPolicy | None = None,
    ) -> None:
        # `http` строится вручную ради двух вещей: явного таймаута сокета и
        # прямого доступа к пулу соединений, который приходится сбрасывать
        # между тиками (см. `reset_connections`).
        self._http = httplib2.Http(timeout=timeout_seconds)
        authorized_http = google_auth_httplib2.AuthorizedHttp(credentials, http=self._http)
        self._service = build("sheets", "v4", http=authorized_http, cache_discovery=False)
        self._spreadsheets = self._service.spreadsheets()

        policy = retry or RetryPolicy()
        self.create_spreadsheet = policy(self._create_spreadsheet)
        self.get_layout = policy(self._get_layout)
        self.batch_update = policy(self._batch_update)
        self.get_values = policy(self._get_values)

    def reset_connections(self) -> None:
        """Закрывает пул keep-alive соединений httplib2.

        httplib2, в отличие от urllib3, не проверяет живость соединения из пула.
        За минуты простоя между тиками Google или NAT успевают закрыть сокет, а
        httplib2 всё равно пишет в него запрос и виснет на чтении до таймаута.
        Поэтому пул сбрасывается в начале каждого тика — следующий вызов откроет
        свежее соединение. Безопасно только когда нет активных запросов.
        """
        for connection in self._http.connections.values():
            with contextlib.suppress(Exception):  # noqa: BLE001 — закрываем как получится
                connection.close()
        self._http.connections.clear()

    async def _create_spreadsheet(
        self,
        title: str,
        *,
        locale: str,
        sheets: list[dict[str, Any]],
    ) -> tuple[str, list[SheetProperties]]:
        """Создаёт документ и возвращает его идентификатор вместе с листами.

        `sheets` описывает листы, которые нужно завести сразу. Передавать их
        обязательно: документ без явного списка Google заводит с собственным
        листом «Лист1» на тысячу строк и двадцать шесть колонок, и тот остаётся
        первой вкладкой навсегда — в `sheet_mappings` его нет, а удалять чужие
        листы сверка не должна.
        """

        def call() -> dict[str, Any]:
            request = self._spreadsheets.create(
                body={
                    "properties": {"title": title, "locale": locale},
                    "sheets": sheets,
                },
                fields="spreadsheetId,sheets.properties(sheetId,title,gridProperties)",
            )
            return to_dict(request.execute())

        body = await anyio.to_thread.run_sync(call)
        spreadsheet_id = body.get("spreadsheetId")
        if not spreadsheet_id:
            raise GoogleApiError("Google не вернул идентификатор созданного документа")
        return str(spreadsheet_id), _parse_sheets(body)

    async def _get_layout(self, spreadsheet_id: str) -> list[SheetProperties]:
        """Возвращает листы документа.

        Маска `fields` не косметика: без неё Google отдаёт документ целиком,
        вместе со значениями всех ячеек всех листов за всю историю.
        """

        def call() -> dict[str, Any]:
            request = self._spreadsheets.get(
                spreadsheetId=spreadsheet_id,
                fields=(
                    "sheets(properties(sheetId,title,gridProperties),"
                    "protectedRanges(protectedRangeId))"
                ),
            )
            return to_dict(request.execute())

        body = await anyio.to_thread.run_sync(call)
        return _parse_sheets(body)

    async def _batch_update(
        self,
        spreadsheet_id: str,
        requests: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Выполняет пачку запросов одним вызовом и возвращает ответы на них.

        Единственный способ что-либо изменить в документе. Вызов атомарен:
        Google применяет либо все запросы, либо ни одного — поэтому лист не
        может остаться наполовину стёртым, как это выходило у старой версии с
        её последовательностью «очистить, записать, оформить».
        """
        if not requests:
            return []

        def call() -> dict[str, Any]:
            request = self._spreadsheets.batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            )
            return to_dict(request.execute())

        body = await anyio.to_thread.run_sync(call)
        return list(body.get("replies", []))

    async def _get_values(self, spreadsheet_id: str, range_a1: str) -> list[list[Any]]:
        """Читает диапазон в неформатированном виде.

        `UNFORMATTED_VALUE` возвращает то, что в ячейке **хранится**: Google сам
        разбирает введённое пользователем «1 000,50» по локали документа и
        отдаёт число. Со `FORMATTED_VALUE` пришлось бы разбирать строку с
        неразрывным пробелом внутри — ровно на этом старая версия и падала.
        """

        def call() -> dict[str, Any]:
            request = self._spreadsheets.values().get(
                spreadsheetId=spreadsheet_id,
                range=range_a1,
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="FORMATTED_STRING",
            )
            return to_dict(request.execute())

        body = await anyio.to_thread.run_sync(call)
        return list(body.get("values", []))


def _parse_sheets(body: dict[str, Any]) -> list[SheetProperties]:
    """Разбирает список листов из ответа Google.

    Общий для `create` и `get`: оба возвращают листы одной и той же формой, и
    два разных разбора со временем разошлись бы.
    """
    layout: list[SheetProperties] = []
    for sheet in body.get("sheets", []):
        props = sheet.get("properties", {})
        grid = props.get("gridProperties", {})
        layout.append(
            SheetProperties(
                sheet_id=int(props["sheetId"]),
                title=str(props.get("title", "")),
                row_count=int(grid.get("rowCount", 0)),
                column_count=int(grid.get("columnCount", 0)),
                protected_range_ids=tuple(
                    int(item["protectedRangeId"])
                    for item in sheet.get("protectedRanges", [])
                    if "protectedRangeId" in item
                ),
            )
        )
    return layout
