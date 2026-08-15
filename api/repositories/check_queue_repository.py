"""Репозиторий очереди чеков."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.check_queue_item import CheckQueueItem
from api.mappers.check_queue_item_mapper import CheckQueueItemMapper
from api.orm.check_queue_item import CheckQueueItemORM
from api.repositories.base import BaseRepository, affected_rows


class CheckQueueRepository(BaseRepository[CheckQueueItemORM, CheckQueueItem]):
    """Доступ к очереди необработанных чеков."""

    orm_type = CheckQueueItemORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CheckQueueItemMapper())

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[CheckQueueItem]:
        """Возвращает чеки документа в порядке поступления."""
        rows = (
            await self._session.scalars(
                select(CheckQueueItemORM)
                .where(CheckQueueItemORM.spreadsheet_id == spreadsheet_id)
                .order_by(CheckQueueItemORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def get_for_spreadsheet(
        self,
        item_id: int,
        spreadsheet_id: int,
    ) -> CheckQueueItem | None:
        """Возвращает чек, только если он принадлежит указанному документу."""
        orm = (
            await self._session.scalars(
                select(CheckQueueItemORM).where(
                    CheckQueueItemORM.id == item_id,
                    CheckQueueItemORM.spreadsheet_id == spreadsheet_id,
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def delete_for_spreadsheet(self, item_id: int, spreadsheet_id: int) -> bool:
        """Удаляет чек из очереди с проверкой принадлежности документу.

        Проверка обязательна: прежний код удалял чек по одному лишь id, поэтому
        запрос с чужим идентификатором вычищал чужую очередь.
        """
        result = await self._session.execute(
            delete(CheckQueueItemORM).where(
                CheckQueueItemORM.id == item_id,
                CheckQueueItemORM.spreadsheet_id == spreadsheet_id,
            )
        )
        await self._session.flush()
        return bool(affected_rows(result))

    async def count_by_spreadsheet(self, spreadsheet_id: int) -> int:
        """Считает чеки в очереди документа."""
        total = await self._session.scalar(
            select(func.count())
            .select_from(CheckQueueItemORM)
            .where(CheckQueueItemORM.spreadsheet_id == spreadsheet_id)
        )
        return int(total or 0)
