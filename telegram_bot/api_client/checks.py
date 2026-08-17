"""Клиент чеков: очередь разбора, кэш типов и запись разобранного чека."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from telegram_bot import constants
from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import CashedRecord, Check, Record


class CommitItem(BaseModel):
    """Позиция, готовая к записи в реестр.

    Тип уходит по **каждой** позиции, включая взятые из кэша: api переучивает
    кэш сам (`CashedRecordRepository.upsert`), и правка типа у уже знакомого
    товара таким образом не может потеряться. В старой версии она и терялась —
    молча.
    """

    model_config = ConfigDict(frozen=True)

    product_name: str
    product_type: str | None
    category_id: int
    amount: Decimal


class NewProductType(BaseModel):
    """Тип товара, который пользователь закрепляет за категорией."""

    model_config = ConfigDict(frozen=True)

    category_id: int
    product_type: str


class ChecksClient:
    """Очередь неразобранных чеков и запись разобранного."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def list_unprocessed(self, spreadsheet_id: int) -> list[Check]:
        """Чеки, ждущие разбора, от самого старого."""
        items = await self._http.get_items(
            f"/spreadsheets/{spreadsheet_id}/checks",
            params={"unprocessed": True},
        )
        return [Check.model_validate(item) for item in items]

    async def delete(self, spreadsheet_id: int, check_id: int) -> None:
        """Удаляет неразобранный чек."""
        await self._http.delete(f"/spreadsheets/{spreadsheet_id}/checks/{check_id}")

    async def cashed_records(self, spreadsheet_id: int) -> list[CashedRecord]:
        """Выученные соответствия «товар → тип» документа."""
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/cashed-records")
        return [CashedRecord.model_validate(item) for item in items]

    async def commit(
        self,
        spreadsheet_id: int,
        *,
        check_id: int,
        source_id: int,
        items: Sequence[CommitItem],
        new_product_types: Sequence[NewProductType] = (),
    ) -> list[Record]:
        """Записывает разобранный чек целиком одним запросом.

        Одним, а не по позиции: новые типы, кэш, N операций и отметка о разборе
        — одна транзакция на стороне api, и ни одна её часть не может уцелеть
        без остальных.
        """
        data = await self._http.post_items(
            f"/spreadsheets/{spreadsheet_id}/checks/commit",
            body={
                "check_id": check_id,
                "source_id": source_id,
                "items": [
                    {
                        "product_name": item.product_name,
                        "product_type": item.product_type,
                        "category_id": item.category_id,
                        "amount": str(item.amount),
                    }
                    for item in items
                ],
                "new_product_types": [
                    {
                        "category_id": assignment.category_id,
                        "product_type": assignment.product_type,
                    }
                    for assignment in new_product_types
                ],
            },
            timeout=constants.WRITE_TIMEOUT_SECONDS,
        )
        return [Record.model_validate(item) for item in data]
