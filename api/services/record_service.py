"""Операции реестра: добавление, удаление, чтение текущего периода."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.logging import get_logger
from api.core.period import now_in_timezone
from api.domain.record import Record
from api.domain.spreadsheet import Spreadsheet
from api.enums import CategoryKind, SheetTarget, SyncTaskKind
from api.exceptions.base import BusinessRuleError, NotFoundError
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.check_repository import CheckRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services._periods import assert_open, ensure_current_period, resolve_period, today_for
from api.services.base import BaseSpreadsheetService

logger = get_logger(__name__)


class RecordService(BaseSpreadsheetService):
    """Бизнес-правила операций: знак суммы, период, устаревание листов."""

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        periods: PeriodRepository,
        categories: CategoryRepository,
        sources: SourceRepository,
        records: RecordRepository,
        cashed_records: CashedRecordRepository,
        checks: CheckRepository,
        tasks: SheetSyncTaskRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._periods = periods
        self._categories = categories
        self._sources = sources
        self._records = records
        self._cashed_records = cashed_records
        self._checks = checks
        self._tasks = tasks

    async def list_by_period(
        self,
        spreadsheet_id: int,
        period_id: int | None = None,
    ) -> list[Record]:
        """Операции периода; без `period_id` — текущего.

        Пустой список, если периода ещё нет: читать его создание не должно.
        """
        spreadsheet = await self._get_ready(spreadsheet_id)
        period = await resolve_period(self._periods, spreadsheet, period_id)
        if period is None or period.id is None:
            return []
        return await self._records.list_by_period(period.id)

    async def create(
        self,
        spreadsheet_id: int,
        *,
        category_id: int,
        source_id: int,
        amount: Decimal,
        notes: str = "",
        product_name: str | None = None,
        product_type: str | None = None,
    ) -> Record:
        """Добавляет операцию и помечает устаревшими зависящие от неё листы.

        Знак суммы ставит вид категории, а не пользователь: снаружи приходит
        модуль. Прежде знак приходил вместе с суммой, и расход с минусом
        превращался в доход.

        Период под сегодняшнюю дату создаётся здесь же, если его ещё нет:
        ждать фонового ролловера нельзя, иначе первая операция после простоя
        упёрлась бы в отсутствующий период.
        """
        if amount <= 0:
            raise BusinessRuleError("Сумма должна быть больше нуля")

        spreadsheet = await self._get_ready(spreadsheet_id)
        category = await self._categories.get_for_spreadsheet(category_id, spreadsheet_id)
        if category is None:
            raise NotFoundError("category")
        source = await self._sources.get_for_spreadsheet(source_id, spreadsheet_id)
        if source is None:
            raise NotFoundError("source")

        today = today_for(spreadsheet)
        period = await ensure_current_period(self._periods, spreadsheet, today)
        assert period.id is not None

        signed = amount if category.kind is CategoryKind.INCOME else -amount
        record = await self._records.add(
            Record(
                spreadsheet_id=spreadsheet_id,
                period_id=period.id,
                category_id=category_id,
                source_id=source_id,
                amount=signed,
                added_at=today,
                notes=notes,
                product_name=product_name,
                product_type=product_type,
            )
        )
        await self._tasks.enqueue_many(_affected_sheets(spreadsheet_id, period.id))
        await self._commit()
        logger.info("Операция %s добавлена в документ %s", record.id, spreadsheet_id)
        return record

    async def delete(self, spreadsheet_id: int, record_id: int | None = None) -> Record:
        """Удаляет операцию (по id или последнюю в текущем периоде).

        Удаление мягкое: разобраться в спорном балансе после ошибочного `/del`
        иначе нечем. Баланс счёта пересчитается сам — он не хранится.

        Вместе с последней живой операцией чека умирает и сам чек. Иначе он
        оставался бы навсегда: разобранный, он не вернётся в очередь `/check`,
        занимает `external_key` — ту же бумажку нельзя отсканировать заново — и
        продолжает висеть строкой на листе-архиве месяца, хотя в реестре от него
        ничего не осталось. Удаление чека тоже мягкое и той же меткой времени:
        это одно событие, а не два.
        """
        spreadsheet = await self._get_ready(spreadsheet_id)
        record = await self._pick(spreadsheet, record_id)
        assert record.id is not None

        period = await self._periods.get_for_spreadsheet(record.period_id, spreadsheet_id)
        if period is None:
            raise NotFoundError("period")
        assert_open(period)

        at = now_in_timezone(spreadsheet.timezone)
        await self._records.soft_delete(record.id, at=at)
        if record.product_name:
            # Кэш «товар → тип» учится на подтверждённых операциях. Если
            # операцию удалили, подтверждения больше нет, и следующий чек должен
            # спросить тип заново, а не повторить ошибку.
            await self._cashed_records.delete_by_product_name(
                spreadsheet_id, record.product_name
            )

        keys = _affected_sheets(spreadsheet_id, record.period_id)
        if record.check_id is not None and not await self._records.exists_by_check(
            record.check_id
        ):
            await self._checks.soft_delete(record.check_id, at=at)
            # Лист-архив месяца потерял строку — его тоже надо перерисовать.
            keys.append(
                (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.CHECKS, record.period_id)
            )
            logger.info(
                "Чек %s удалён вместе с последней своей операцией в документе %s",
                record.check_id,
                spreadsheet_id,
            )

        await self._tasks.enqueue_many(keys)
        await self._commit()
        logger.info("Операция %s удалена из документа %s", record.id, spreadsheet_id)
        return record

    async def _pick(self, spreadsheet: Spreadsheet, record_id: int | None) -> Record:
        """Находит операцию по id или последнюю в текущем периоде."""
        assert spreadsheet.id is not None
        if record_id is not None:
            record = await self._records.get_for_spreadsheet(record_id, spreadsheet.id)
            if record is None:
                raise NotFoundError("record")
            return record

        period = await self._periods.get_containing(spreadsheet.id, today_for(spreadsheet))
        if period is None or period.id is None:
            raise NotFoundError("record")
        record = await self._records.get_last_in_period(period.id)
        if record is None:
            raise NotFoundError("record")
        return record


def _affected_sheets(spreadsheet_id: int, period_id: int) -> list[TaskKey]:
    """Листы, устаревающие от любой правки операции.

    Операция попадает в реестр периода, в дневную статистику своей категории и
    меняет баланс счёта — то есть три листа сразу.
    """
    return [
        (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period_id),
        (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.STATISTICS, period_id),
        (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None),
    ]
