"""Репозиторий сохранённых чеков."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.check import Check
from api.enums import CheckKind
from api.mappers.check_mapper import CheckMapper
from api.orm.check import CheckORM
from api.repositories.base import BaseRepository


class CheckRepository(BaseRepository[CheckORM, Check]):
    """Доступ к сохранённым чекам документа."""

    orm_type = CheckORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CheckMapper())

    async def get_by_external_key(
        self,
        spreadsheet_id: int,
        kind: CheckKind,
        external_key: str,
    ) -> Check | None:
        """Находит уже сохранённый чек по ключу формата.

        Ключ вычисляет парсер (для ФНС — «ФН:ФД:ФП»), поэтому вид входит в
        условие: один и тот же набор цифр в двух форматах — разные чеки.
        """
        orm = (
            await self._session.scalars(
                select(CheckORM).where(
                    CheckORM.spreadsheet_id == spreadsheet_id,
                    CheckORM.kind == kind,
                    CheckORM.external_key == external_key,
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[Check]:
        """Возвращает чеки документа в порядке поступления."""
        rows = (
            await self._session.scalars(
                select(CheckORM)
                .where(CheckORM.spreadsheet_id == spreadsheet_id)
                .order_by(CheckORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)
