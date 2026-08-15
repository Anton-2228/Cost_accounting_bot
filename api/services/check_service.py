"""Очередь чеков, кэш «товар → тип» и запись разобранного чека."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.core.logging import get_logger
from api.domain.cashed_record import CashedRecord
from api.domain.category import Category
from api.domain.check_item import CheckItem, ProductTypeAssignment
from api.domain.check_queue_item import CheckQueueItem
from api.domain.record import Record
from api.enums import CategoryKind, SheetTarget, SyncTaskKind
from api.exceptions.base import NotFoundError
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.check_queue_repository import CheckQueueRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services._periods import ensure_current_period, today_for
from api.services.base import BaseSpreadsheetService

logger = get_logger(__name__)


class CheckService(BaseSpreadsheetService):
    """Разбор чека доводится ботом, а api записывает готовый результат.

    Модель, стадии диалога и подтверждения пользователя остаются в боте: они
    перемежаются вопросами и живут в его состоянии. Сюда приезжает уже
    разложенный чек, и весь он записывается **одной транзакцией** — иначе
    прерывание на середине оставило бы половину чека в реестре, а половину
    потеряло.
    """

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
        queue: CheckQueueRepository,
        tasks: SheetSyncTaskRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._periods = periods
        self._categories = categories
        self._sources = sources
        self._records = records
        self._cashed_records = cashed_records
        self._queue = queue
        self._tasks = tasks

    # --- очередь ---

    async def list_queue(self, spreadsheet_id: int) -> list[CheckQueueItem]:
        """Чеки, ожидающие разбора."""
        await self._get_ready(spreadsheet_id)
        return await self._queue.list_by_spreadsheet(spreadsheet_id)

    async def enqueue(self, spreadsheet_id: int, check_text: str) -> CheckQueueItem:
        """Кладёт сырой чек в очередь.

        Готовность таблицы не проверяется: очередь наполняет внешний источник,
        которому незачем знать, дорисован ли уже Google-документ. Чек полежит и
        дождётся разбора.
        """
        await self._get(spreadsheet_id)
        item = await self._queue.add(
            CheckQueueItem(spreadsheet_id=spreadsheet_id, check_text=check_text)
        )
        await self._commit()
        return item

    async def delete_from_queue(self, spreadsheet_id: int, item_id: int) -> None:
        """Убирает чек из очереди (пользователь его пропустил или разобрал)."""
        await self._get_ready(spreadsheet_id)
        if not await self._queue.delete_for_spreadsheet(item_id, spreadsheet_id):
            raise NotFoundError("check")
        await self._commit()

    # --- кэш ---

    async def list_cashed_records(self, spreadsheet_id: int) -> list[CashedRecord]:
        """Выученные соответствия «товар → тип» документа."""
        await self._get_ready(spreadsheet_id)
        return await self._cashed_records.list_by_spreadsheet(spreadsheet_id)

    # --- запись чека ---

    async def commit_check(
        self,
        spreadsheet_id: int,
        *,
        source_id: int,
        items: Sequence[CheckItem],
        new_product_types: Sequence[ProductTypeAssignment] = (),
        check_id: int | None = None,
        check_json: str | None = None,
    ) -> list[Record]:
        """Записывает разобранный чек: типы товаров, кэш, операции, снятие с очереди.

        Всё перечисленное — одна транзакция. Порядок внутри значения не имеет,
        важно лишь то, что ни одна её часть не может уцелеть без остальных.
        """
        spreadsheet = await self._get_ready(spreadsheet_id)
        if await self._sources.get_for_spreadsheet(source_id, spreadsheet_id) is None:
            raise NotFoundError("source")

        # Все категории документа, а не только активные: неактивная категория
        # скрыта из подсказок, но продолжает существовать, и позиция чека,
        # разложенная в неё до того, как её скрыли, не должна валить запись
        # всего чека целиком.
        categories = {
            category.id: category
            for category in await self._categories.list_by_spreadsheet(spreadsheet_id)
            if category.id is not None
        }
        await self._assign_product_types(new_product_types, categories)

        today = today_for(spreadsheet)
        period = await ensure_current_period(self._periods, spreadsheet, today)
        assert period.id is not None

        created: list[Record] = []
        for item in items:
            category = categories.get(item.category_id)
            if category is None:
                raise NotFoundError("category")

            signed = item.amount if category.kind is CategoryKind.INCOME else -item.amount
            created.append(
                await self._records.add(
                    Record(
                        spreadsheet_id=spreadsheet_id,
                        period_id=period.id,
                        category_id=item.category_id,
                        source_id=source_id,
                        amount=signed,
                        added_at=today,
                        product_name=item.product_name,
                        product_type=item.product_type,
                        check_json=check_json,
                    )
                )
            )
            if item.product_type:
                await self._cashed_records.upsert(
                    CashedRecord(
                        spreadsheet_id=spreadsheet_id,
                        product_name=item.product_name,
                        product_type=item.product_type,
                    )
                )

        if check_id is not None:
            await self._queue.delete_for_spreadsheet(check_id, spreadsheet_id)

        keys: list[TaskKey] = [
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period.id),
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.STATISTICS, period.id),
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None),
        ]
        if new_product_types:
            keys.append((spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.CATEGORIES, None))
        await self._tasks.enqueue_many(keys)

        await self._commit()
        logger.info("Чек из %s позиций записан в документ %s", len(created), spreadsheet_id)
        return created

    async def _assign_product_types(
        self,
        assignments: Sequence[ProductTypeAssignment],
        categories: Mapping[int, Category],
    ) -> None:
        """Закрепляет новые типы товаров за категориями.

        Категория по умолчанию для расходов типов не получает никогда: это
        корзина для всего, что не удалось разложить, и обучение на её
        содержимом притянуло бы туда же следующие чеки.
        """
        for assignment in assignments:
            category = categories.get(assignment.category_id)
            if category is None:
                raise NotFoundError("category")
            if category.title == constants.DEFAULT_EXPENSE_CATEGORY:
                continue
            await self._categories.add_product_type(
                assignment.category_id, assignment.product_type
            )
