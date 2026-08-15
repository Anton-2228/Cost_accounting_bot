"""Базовый сервис: документ, его готовность и общая граница транзакции.

Каждый сервис получает сессию и нужные репозитории в `__init__`, а транзакцию
завершает ровно одним `commit`. Мутация и постановка задач в очередь листов
всегда попадают в одну транзакцию: иначе возможно состояние «деньги списаны, но
лист об этом не узнает никогда».
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.transaction import commit
from api.domain.spreadsheet import Spreadsheet
from api.exceptions.base import ConflictError, NotFoundError
from api.repositories.spreadsheet_repository import SpreadsheetRepository

#: Причина конфликта для бота: документ есть, но Google-таблицы ещё нет.
NOT_READY_REASON = "spreadsheet_not_ready"


class BaseSpreadsheetService:
    """Общий предок сервисов, работающих в рамках одного документа."""

    def __init__(self, session: AsyncSession, spreadsheets: SpreadsheetRepository) -> None:
        self._session = session
        self._spreadsheets = spreadsheets

    async def _commit(self) -> None:
        """Фиксирует транзакцию. Единственная точка коммита в сервисе."""
        await commit(self._session)

    async def _get(self, spreadsheet_id: int) -> Spreadsheet:
        """Возвращает документ или бросает 404."""
        spreadsheet = await self._spreadsheets.get_by_id(spreadsheet_id)
        if spreadsheet is None:
            raise NotFoundError("spreadsheet")
        return spreadsheet

    async def _get_ready(self, spreadsheet_id: int) -> Spreadsheet:
        """Возвращает документ, у которого уже есть Google-таблица.

        Пока `google_sheets_service` не создал документ и не проставил его id,
        работать с таблицей нельзя: пользователю некуда смотреть, а операция,
        принятая «вслепую», выглядела бы для него потерянной. Служебные
        эндпоинты (сама простановка id, очередь, уведомления) этой проверки не
        делают — иначе систему было бы нечем вывести из этого состояния.
        """
        spreadsheet = await self._get(spreadsheet_id)
        if spreadsheet.google_spreadsheet_id is None:
            raise ConflictError(
                "Google-таблица ещё не создана",
                details={"reason": NOT_READY_REASON},
            )
        return spreadsheet
