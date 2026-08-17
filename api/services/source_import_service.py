"""Вчитывание правок листа `Bills` в базу."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api import validation
from api.core import messages
from api.core.logging import get_logger
from api.core.period import now_in_timezone
from api.domain.sheet_import_result import SheetImportResult
from api.domain.source import Source
from api.enums import EntityStatus, NotificationKind, SheetTarget, SyncTaskKind
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.base import BaseSpreadsheetService

logger = get_logger(__name__)


class SourceImportService(BaseSpreadsheetService):
    """Лист `Bills` — единственный способ править список счетов.

    Колонка `Current balance` не читается: баланс вычисляется из операций и
    переводов. Прежняя версия хранила его в БД и переписывала с листа, поэтому
    любое расхождение закреплялось навсегда.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        sources: SourceRepository,
        periods: PeriodRepository,
        tasks: SheetSyncTaskRepository,
        notifications: UserNotificationRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._sources = sources
        self._periods = periods
        self._tasks = tasks
        self._notifications = notifications

    async def import_rows(
        self,
        spreadsheet_id: int,
        rows: Sequence[Sequence[str]],
    ) -> SheetImportResult:
        """Применяет лист целиком. Ошибка означает, что не записано ничего."""
        spreadsheet = await self._get(spreadsheet_id)
        padded = validation.pad(rows, validation.SOURCE_WIDTH)
        existing = await self._sources.list_by_spreadsheet(spreadsheet_id)
        by_id = {source.id: source for source in existing if source.id is not None}

        error = validation.validate_source_rows(padded, set(by_id))
        if error is not None:
            await self._notifications.notify(
                spreadsheet_id, NotificationKind.IMPORT_ERROR, error
            )
            await self._commit()
            logger.info("Импорт счетов документа %s отклонён: %s", spreadsheet_id, error)
            return SheetImportResult(error=error)

        result = SheetImportResult()
        aliases: dict[int, list[str]] = {}
        deleted_at = now_in_timezone(spreadsheet.timezone)

        for row in padded:
            if validation.is_blank(row):
                continue
            if not validation.is_cleared(row, validation.SOURCE_MEANINGFUL_FIELDS):
                continue
            source_id = validation.parse_id(row[0])
            assert source_id is not None
            await self._sources.soft_delete(source_id, at=deleted_at)
            # Псевдонимы уникальны в пределах документа независимо от
            # `deleted_at`, поэтому у удалённого счёта их надо снять — иначе имя
            # останется занятым навсегда.
            aliases[source_id] = []
            result.deleted += 1

        for row in padded:
            if validation.is_blank(row):
                continue
            if validation.is_cleared(row, validation.SOURCE_MEANINGFUL_FIELDS):
                continue
            source_id = validation.parse_id(row[0])
            if source_id is None:
                continue

            updated = await self._sources.update(
                Source(
                    id=source_id,
                    spreadsheet_id=spreadsheet_id,
                    status=_status(row[1]),
                    title=row[2].strip(),
                    start_balance=_start_balance(row[4]),
                )
            )
            assert updated is not None
            aliases[source_id] = validation.parse_aliases(row[3], row[2])
            result.updated += 1

        for row in padded:
            if validation.is_blank(row) or row[0].strip() != "":
                continue
            created = await self._sources.add(
                Source(
                    spreadsheet_id=spreadsheet_id,
                    status=_status(row[1]),
                    title=row[2].strip(),
                    start_balance=_start_balance(row[4]),
                )
            )
            assert created.id is not None
            aliases[created.id] = validation.parse_aliases(row[3], row[2])
            result.created += 1

        await self._sources.replace_associations_bulk(aliases)
        await self._tasks.enqueue_many(await self._affected_sheets(spreadsheet_id))
        # Уведомление уходит в той же транзакции, что и сами правки: иначе
        # появилось бы состояние «пользователю сообщили об успехе, а импорт
        # откатился».
        await self._notifications.notify(
            spreadsheet_id,
            NotificationKind.IMPORT_OK,
            messages.import_ok(messages.BILLS_SHEET_TITLE),
        )
        await self._commit()
        logger.info(
            "Импорт счетов документа %s: +%s ~%s -%s",
            spreadsheet_id,
            result.created,
            result.updated,
            result.deleted,
        )
        return result

    async def _affected_sheets(self, spreadsheet_id: int) -> list[TaskKey]:
        """Листы, устаревающие после правки счетов: `Bills` и реестр операций."""
        keys: list[TaskKey] = [(spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None)]
        for period in await self._periods.list_open(spreadsheet_id):
            keys.append(
                (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period.id)
            )
        return keys


def _status(cell: str) -> EntityStatus:
    """Колонка `Active`: 1 — активен, 0 — скрыт из подсказок."""
    return EntityStatus.ACTIVE if cell == "1" else EntityStatus.INACTIVE


def _start_balance(cell: str) -> Decimal:
    """Начальный остаток. Валидация уже подтвердила, что это число."""
    value = validation.parse_money(cell)
    assert value is not None
    return value
