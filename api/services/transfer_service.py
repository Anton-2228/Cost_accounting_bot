"""Переводы денег между счетами одного документа."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.core.period import now_in_timezone
from api.domain.spreadsheet import Spreadsheet
from api.domain.transfer import Transfer
from api.enums import SheetTarget, SyncTaskKind
from api.exceptions.base import BusinessRuleError, NotFoundError
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.transfer_repository import TransferRepository
from api.services._periods import assert_open, ensure_current_period, resolve_period, today_for
from api.services.base import BaseSpreadsheetService

logger = get_logger(__name__)


class TransferService(BaseSpreadsheetService):
    """Перекладывание денег между счетами.

    В доходы и расходы перевод не попадает: деньги не появились и не исчезли,
    поэтому лист статистики он не трогает. А вот в реестре операций перевод
    виден — прежняя версия молча двигала два баланса, не оставляя следа, и
    ошибочный перевод нельзя было ни найти, ни отменить.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        periods: PeriodRepository,
        sources: SourceRepository,
        transfers: TransferRepository,
        tasks: SheetSyncTaskRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._periods = periods
        self._sources = sources
        self._transfers = transfers
        self._tasks = tasks

    async def list_by_period(
        self,
        spreadsheet_id: int,
        period_id: int | None = None,
    ) -> list[Transfer]:
        """Переводы периода; без `period_id` — текущего."""
        spreadsheet = await self._get_ready(spreadsheet_id)
        period = await resolve_period(self._periods, spreadsheet, period_id)
        if period is None or period.id is None:
            return []
        return await self._transfers.list_by_period(period.id)

    async def create(
        self,
        spreadsheet_id: int,
        *,
        from_source_id: int,
        to_source_id: int,
        amount: Decimal,
        notes: str = "",
    ) -> Transfer:
        """Переводит сумму между счетами одной транзакцией.

        Обе стороны перевода — одна строка, а не два движения баланса: потерять
        половину перевода при сбое теперь физически нечем.
        """
        if amount <= 0:
            raise BusinessRuleError("Сумма должна быть больше нуля")
        if from_source_id == to_source_id:
            raise BusinessRuleError("Счёт отправителя совпадает с получателем")

        spreadsheet = await self._get_ready(spreadsheet_id)
        for source_id in (from_source_id, to_source_id):
            if await self._sources.get_for_spreadsheet(source_id, spreadsheet_id) is None:
                raise NotFoundError("source")

        today = today_for(spreadsheet)
        period = await ensure_current_period(self._periods, spreadsheet, today)
        assert period.id is not None

        transfer = await self._transfers.add(
            Transfer(
                spreadsheet_id=spreadsheet_id,
                period_id=period.id,
                from_source_id=from_source_id,
                to_source_id=to_source_id,
                amount=amount,
                added_at=today,
                notes=notes,
            )
        )
        await self._tasks.enqueue_many(_affected_sheets(spreadsheet_id, period.id))
        await self._commit()
        logger.info("Перевод %s добавлен в документ %s", transfer.id, spreadsheet_id)
        return transfer

    async def delete(self, spreadsheet_id: int, transfer_id: int | None = None) -> Transfer:
        """Удаляет перевод (по id или последний в текущем периоде)."""
        spreadsheet = await self._get_ready(spreadsheet_id)
        transfer = await self._pick(spreadsheet, transfer_id)
        assert transfer.id is not None

        period = await self._periods.get_for_spreadsheet(transfer.period_id, spreadsheet_id)
        if period is None:
            raise NotFoundError("period")
        assert_open(period)

        await self._transfers.soft_delete(
            transfer.id, at=now_in_timezone(spreadsheet.timezone)
        )
        await self._tasks.enqueue_many(_affected_sheets(spreadsheet_id, transfer.period_id))
        await self._commit()
        logger.info("Перевод %s удалён из документа %s", transfer.id, spreadsheet_id)
        return transfer

    async def _pick(self, spreadsheet: Spreadsheet, transfer_id: int | None) -> Transfer:
        """Находит перевод по id или последний в текущем периоде."""
        assert spreadsheet.id is not None
        if transfer_id is not None:
            transfer = await self._transfers.get_for_spreadsheet(transfer_id, spreadsheet.id)
            if transfer is None:
                raise NotFoundError("transfer")
            return transfer

        period = await self._periods.get_containing(spreadsheet.id, today_for(spreadsheet))
        if period is None or period.id is None:
            raise NotFoundError("transfer")
        transfer = await self._transfers.get_last_in_period(period.id)
        if transfer is None:
            raise NotFoundError("transfer")
        return transfer


def _affected_sheets(spreadsheet_id: int, period_id: int) -> list[TaskKey]:
    """Листы, устаревающие от правки перевода: реестр операций и балансы."""
    return [
        (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period_id),
        (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None),
    ]
