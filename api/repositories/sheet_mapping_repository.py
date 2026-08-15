"""Репозиторий соответствий «адресат перерисовки → лист документа»."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.sheet_mapping import SheetMapping
from api.enums import SheetTarget
from api.mappers.sheet_mapping_mapper import SheetMappingMapper
from api.orm.sheet_mapping import SheetMappingORM
from api.repositories.base import BaseRepository, affected_rows


class SheetMappingRepository(BaseRepository[SheetMappingORM, SheetMapping]):
    """Доступ к сведениям о физическом расположении листов."""

    orm_type = SheetMappingORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SheetMappingMapper())

    async def upsert(self, mapping: SheetMapping) -> SheetMapping:
        """Записывает расположение листа, обновляя существующую запись.

        Вызывается **после** подтверждения от Google: наличие строки означает
        «лист создан». Прежняя версия не хранила ничего, полагаясь на
        соглашение об имени листа, и сбой при создании оставлял документ
        сломанным навсегда — указатель периода уже сдвинулся, а листа не было.
        """
        stmt = (
            pg_insert(SheetMappingORM)
            .values(
                spreadsheet_id=mapping.spreadsheet_id,
                target=mapping.target,
                period_id=mapping.period_id,
                google_sheet_id=mapping.google_sheet_id,
                title=mapping.title,
            )
            .on_conflict_do_update(
                constraint="uq_sheet_mappings_key",
                set_={
                    "google_sheet_id": mapping.google_sheet_id,
                    "title": mapping.title,
                    "updated_at": func.now(),
                },
            )
            .returning(SheetMappingORM)
        )
        orm = (await self._session.scalars(stmt)).one()
        await self._session.flush()
        return self._mapper.to_domain(orm)

    async def get(
        self,
        spreadsheet_id: int,
        target: SheetTarget,
        period_id: int | None = None,
    ) -> SheetMapping | None:
        """Находит расположение конкретного листа."""
        stmt = select(SheetMappingORM).where(
            SheetMappingORM.spreadsheet_id == spreadsheet_id,
            SheetMappingORM.target == target,
        )
        stmt = stmt.where(
            SheetMappingORM.period_id.is_(None)
            if period_id is None
            else SheetMappingORM.period_id == period_id
        )
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[SheetMapping]:
        """Возвращает все известные листы документа."""
        rows = (
            await self._session.scalars(
                select(SheetMappingORM)
                .where(SheetMappingORM.spreadsheet_id == spreadsheet_id)
                .order_by(SheetMappingORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def delete_for_spreadsheet(self, mapping_id: int, spreadsheet_id: int) -> bool:
        """Удаляет запись о листе с проверкой принадлежности документу."""
        result = await self._session.execute(
            delete(SheetMappingORM).where(
                SheetMappingORM.id == mapping_id,
                SheetMappingORM.spreadsheet_id == spreadsheet_id,
            )
        )
        await self._session.flush()
        return bool(affected_rows(result))
