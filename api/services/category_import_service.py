"""Вчитывание правок листа `Categories` в базу."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from api import validation
from api.core.logging import get_logger
from api.core.period import now_in_timezone
from api.domain.category import Category
from api.domain.sheet_import_result import SheetImportResult
from api.enums import CategoryKind, EntityStatus, NotificationKind, SheetTarget, SyncTaskKind
from api.exceptions.base import NotFoundError
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.base import BaseSpreadsheetService

logger = get_logger(__name__)


class CategoryImportService(BaseSpreadsheetService):
    """Лист `Categories` — единственный способ править справочник категорий.

    Сервис принимает **сырые строки** от `google_sheets_service`: сам он в
    Google не ходит. Строка без ID создаёт категорию, строка с ID обновляет её,
    очищенная строка (ID остался, поля стёрты) удаляет.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        categories: CategoryRepository,
        periods: PeriodRepository,
        cashed_records: CashedRecordRepository,
        tasks: SheetSyncTaskRepository,
        notifications: UserNotificationRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._categories = categories
        self._periods = periods
        self._cashed_records = cashed_records
        self._tasks = tasks
        self._notifications = notifications

    async def import_rows(
        self,
        spreadsheet_id: int,
        rows: Sequence[Sequence[str]],
    ) -> SheetImportResult:
        """Применяет лист целиком. Ошибка означает, что не записано ничего."""
        spreadsheet = await self._get(spreadsheet_id)
        padded = validation.pad(rows, validation.CATEGORY_WIDTH)
        existing = await self._categories.list_by_spreadsheet(spreadsheet_id)
        by_id = {category.id: category for category in existing if category.id is not None}

        error = validation.validate_category_rows(padded, set(by_id))
        if error is not None:
            await self._notifications.notify(
                spreadsheet_id, NotificationKind.IMPORT_ERROR, error
            )
            await self._commit()
            logger.info("Импорт категорий документа %s отклонён: %s", spreadsheet_id, error)
            return SheetImportResult(error=error)

        result = SheetImportResult()
        aliases: dict[int, list[str]] = {}
        product_types: dict[int, list[str]] = {}
        dropped_types: list[str] = []
        deleted_at = now_in_timezone(spreadsheet.timezone)

        # Порядок важен: сначала удаления, потом обновления, и только затем
        # создание. Название и псевдоним уникальны в пределах документа, поэтому
        # строка, забирающая имя только что удалённой категории, обязана
        # выполняться после неё.
        for row in padded:
            if validation.is_blank(row):
                continue
            if not validation.is_cleared(row, validation.CATEGORY_MEANINGFUL_FIELDS):
                continue
            category_id = validation.parse_id(row[0])
            assert category_id is not None
            category = by_id.pop(category_id)
            await self._categories.soft_delete(category_id, at=deleted_at)
            # Псевдонимы снимаем и с удалённой категории: их уникальность
            # действует на весь документ независимо от `deleted_at`, иначе имя
            # осталось бы занятым навсегда.
            aliases[category_id] = []
            product_types[category_id] = []
            dropped_types += category.product_types
            result.deleted += 1

        for row in padded:
            if validation.is_blank(row):
                continue
            if validation.is_cleared(row, validation.CATEGORY_MEANINGFUL_FIELDS):
                continue
            category_id = validation.parse_id(row[0])
            if category_id is None:
                continue

            current = by_id.get(category_id)
            if current is None:
                # Сюда не попасть: валидация уже отвергла и незнакомые ID, и
                # повторы. Проверка стоит на случай, если появится третий путь
                # записи: 404 читается, а `KeyError` превратился бы в 500.
                raise NotFoundError("category")
            updated = await self._categories.update(
                Category(
                    id=category_id,
                    spreadsheet_id=spreadsheet_id,
                    kind=_kind(row),
                    status=_status(row[1]),
                    title=row[4].strip(),
                )
            )
            assert updated is not None
            aliases[category_id] = validation.parse_aliases(row[5], row[4])
            product_types[category_id] = validation.parse_product_types(row[6])
            dropped_types += set(current.product_types) - set(product_types[category_id])
            result.updated += 1

        for row in padded:
            if validation.is_blank(row) or row[0].strip() != "":
                continue
            created = await self._categories.add(
                Category(
                    spreadsheet_id=spreadsheet_id,
                    kind=_kind(row),
                    status=_status(row[1]),
                    title=row[4].strip(),
                )
            )
            assert created.id is not None
            aliases[created.id] = validation.parse_aliases(row[5], row[4])
            product_types[created.id] = validation.parse_product_types(row[6])
            result.created += 1

        # Наборы записываются одним заходом на весь документ: снять все старые,
        # сделать flush, вставить новые. По одной категории это неисполнимо —
        # обмен псевдонимами между двумя категориями упёрся бы в уникальный ключ.
        await self._categories.replace_associations_bulk(aliases)
        await self._categories.replace_product_types_bulk(product_types)

        if dropped_types:
            # Кэш «товар → тип» ссылался на типы, которых больше нет ни у одной
            # категории. Оставить его — значит раскладывать будущие чеки по
            # исчезнувшим типам.
            await self._cashed_records.delete_by_product_types(spreadsheet_id, dropped_types)

        await self._tasks.enqueue_many(await self._affected_sheets(spreadsheet_id))
        await self._commit()
        logger.info(
            "Импорт категорий документа %s: +%s ~%s -%s",
            spreadsheet_id,
            result.created,
            result.updated,
            result.deleted,
        )
        return result

    async def _affected_sheets(self, spreadsheet_id: int) -> list[TaskKey]:
        """Листы, устаревающие после правки справочника категорий.

        Кроме самого листа `Categories` перерисовки требуют реестр операций
        (в нём печатается название категории) и статистика (её строки — это
        активные категории).
        """
        keys: list[TaskKey] = [
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.CATEGORIES, None)
        ]
        for period in await self._periods.list_open(spreadsheet_id):
            keys += [
                (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period.id),
                (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.STATISTICS, period.id),
            ]
        return keys


def _status(cell: str) -> EntityStatus:
    """Колонка `Active`: 1 — активна, 0 — скрыта из подсказок."""
    return EntityStatus.ACTIVE if cell == "1" else EntityStatus.INACTIVE


def _kind(row: Sequence[str]) -> CategoryKind:
    """Вид категории по колонкам `Income`/`Cost` (валидация уже проверила пару)."""
    return CategoryKind.INCOME if row[2] == "1" else CategoryKind.EXPENSE
