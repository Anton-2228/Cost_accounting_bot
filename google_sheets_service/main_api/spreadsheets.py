"""Клиент документа: сам документ, доступы и справочники."""

from __future__ import annotations

import httpx

from google_sheets_service.main_api.dto import (
    Access,
    Category,
    Source,
    SourceBalance,
    Spreadsheet,
)
from google_sheets_service.main_api.http import ApiHttpClient


class SpreadsheetsApiClient:
    """Учётная таблица и всё, что читается для её листов."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def get(self, spreadsheet_id: int) -> Spreadsheet:
        """Документ по идентификатору."""
        body = await self._http.get_data(f"/spreadsheets/{spreadsheet_id}")
        assert body is not None  # без allow_404 отсутствие документа — это ApiError
        return Spreadsheet.from_json(body)

    async def set_google_id(self, spreadsheet_id: int, google_spreadsheet_id: str) -> Spreadsheet:
        """Привязывает созданный Google-документ.

        Идемпотентно для того же идентификатора: сервис мог создать документ и
        потерять ответ. Попытка привязать другой документ — конфликт.
        """
        body = await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/google-id",
            body={"google_spreadsheet_id": google_spreadsheet_id},
            expected=httpx.codes.OK,
        )
        return Spreadsheet.from_json(body)

    async def list_pending_accesses(self, spreadsheet_id: int) -> list[Access]:
        """Доступы, которые предстоит выдать."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/accesses",
            params={"pending_only": True},
        )
        return [Access.from_json(item) for item in items]

    async def mark_access_granted(self, spreadsheet_id: int, access_id: int) -> None:
        """Отмечает доступ выданным."""
        await self._http.post_empty(
            f"/spreadsheets/{spreadsheet_id}/accesses/{access_id}/granted"
        )

    async def mark_access_failed(self, spreadsheet_id: int, access_id: int) -> None:
        """Сообщает, что Google отказался выдать доступ на эту почту.

        Api удалит запись и уведомит пользователя: неверный адрес иначе попадал
        бы в каждую последующую сверку скелета.
        """
        await self._http.post_empty(
            f"/spreadsheets/{spreadsheet_id}/accesses/{access_id}/failed"
        )

    async def list_categories(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Category]:
        """Категории документа.

        `include_deleted` нужен реестру операций: удаление мягкое, а операции
        удалённой категории остаются навсегда, и колонке `Category` неоткуда
        было бы взять название.
        """
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/categories",
            params={"only_active": only_active, "include_deleted": include_deleted},
        )
        return [Category.from_json(item) for item in items]

    async def list_sources(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Source]:
        """Счета документа. Параметры — как у категорий."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/sources",
            params={"only_active": only_active, "include_deleted": include_deleted},
        )
        return [Source.from_json(item) for item in items]

    async def list_balances(self, spreadsheet_id: int) -> list[SourceBalance]:
        """Текущие балансы счетов — колонка `Current balance` листа `Bills`."""
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/balances")
        return [SourceBalance.from_json(item) for item in items]
