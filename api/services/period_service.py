"""Чтение учётных периодов и дневных итогов по категориям."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.category_daily_total import CategoryDailyTotal
from api.domain.period import Period
from api.exceptions.base import NotFoundError
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services._periods import resolve_period, today_for
from api.services.base import BaseSpreadsheetService


class PeriodService(BaseSpreadsheetService):
    """Периоды документа и статистика по ним.

    Только чтение: период создают операция (лениво, под сегодняшнюю дату) и
    ролловер. Запрос на чтение ничего не создаёт — иначе `GET` менял бы данные, а
    открытый период мог бы появиться от одного лишь просмотра архива.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        periods: PeriodRepository,
        records: RecordRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._periods = periods
        self._records = records

    async def list_all(self, spreadsheet_id: int) -> list[Period]:
        """Все периоды документа по возрастанию даты начала."""
        await self._get_ready(spreadsheet_id)
        return await self._periods.list_by_spreadsheet(spreadsheet_id)

    async def current(self, spreadsheet_id: int) -> Period:
        """Период, которому принадлежит сегодняшний день документа."""
        spreadsheet = await self._get_ready(spreadsheet_id)
        period = await self._periods.get_containing(spreadsheet_id, today_for(spreadsheet))
        if period is None:
            raise NotFoundError("period")
        return period

    async def daily_totals(
        self,
        spreadsheet_id: int,
        period_id: int | None = None,
    ) -> list[CategoryDailyTotal]:
        """Дневные итоги по категориям за период; без `period_id` — за текущий.

        Из этого строится лист статистики: по строке на категорию и по колонке на
        день периода. Суммы знаковые и в `Decimal` — округлять их нельзя нигде по
        дороге к листу.
        """
        spreadsheet = await self._get_ready(spreadsheet_id)
        period = await resolve_period(self._periods, spreadsheet, period_id)
        if period is None or period.id is None:
            return []
        return await self._records.daily_totals_by_category(period.id)
