"""Репозиторий кэша «название товара → тип»."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.cashed_record import CashedRecord
from api.mappers.cashed_record_mapper import CashedRecordMapper
from api.orm.cashed_record import CashedRecordORM
from api.repositories.base import BaseRepository, affected_rows


class CashedRecordRepository(BaseRepository[CashedRecordORM, CashedRecord]):
    """Доступ к выученным соответствиям товаров и типов."""

    orm_type = CashedRecordORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CashedRecordMapper())

    async def get(self, spreadsheet_id: int, product_name: str) -> CashedRecord | None:
        """Находит запись кэша по названию товара."""
        orm = (
            await self._session.scalars(
                select(CashedRecordORM).where(
                    CashedRecordORM.spreadsheet_id == spreadsheet_id,
                    CashedRecordORM.product_name == product_name,
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def upsert(self, record: CashedRecord) -> CashedRecord:
        """Запоминает соответствие, перезаписывая тип при повторном обучении.

        Уникальность действует в пределах документа, поэтому конфликт возможен
        только со своей же прошлой записью — его и разрешаем обновлением.
        В старой схеме `product_name` был уникален глобально: первый же
        пользователь, закэшировавший «молоко», ломал кэширование этого слова
        всем остальным, а ошибка глушилась и никак не объяснялась.
        """
        stmt = (
            pg_insert(CashedRecordORM)
            .values(
                spreadsheet_id=record.spreadsheet_id,
                product_name=record.product_name,
                product_type=record.product_type,
            )
            .on_conflict_do_update(
                constraint="uq_cashed_records_spreadsheet_id_product_name",
                set_={"product_type": record.product_type, "updated_at": func.now()},
            )
            .returning(CashedRecordORM)
        )
        orm = (await self._session.scalars(stmt)).one()
        await self._session.flush()
        return self._mapper.to_domain(orm)

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[CashedRecord]:
        """Возвращает весь кэш документа."""
        rows = (
            await self._session.scalars(
                select(CashedRecordORM)
                .where(CashedRecordORM.spreadsheet_id == spreadsheet_id)
                .order_by(CashedRecordORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def delete_by_product_name(self, spreadsheet_id: int, product_name: str) -> int:
        """Забывает соответствие для конкретного товара."""
        result = await self._session.execute(
            delete(CashedRecordORM).where(
                CashedRecordORM.spreadsheet_id == spreadsheet_id,
                CashedRecordORM.product_name == product_name,
            )
        )
        await self._session.flush()
        return affected_rows(result)

    async def delete_by_product_types(
        self,
        spreadsheet_id: int,
        product_types: Sequence[str],
    ) -> int:
        """Забывает все соответствия для указанных типов товаров.

        Нужно, когда тип перестаёт принадлежать категории: иначе кэш продолжал
        бы раскладывать позиции чека по типу, которого больше нет.
        """
        if not product_types:
            return 0
        result = await self._session.execute(
            delete(CashedRecordORM).where(
                CashedRecordORM.spreadsheet_id == spreadsheet_id,
                CashedRecordORM.product_type.in_(product_types),
            )
        )
        await self._session.flush()
        return affected_rows(result)
