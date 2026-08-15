"""Репозиторий источников денег, включая агрегат баланса."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal

from sqlalchemy import ColumnElement, delete, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from api.core.text import normalize_terms
from api.db.column_types import MONEY
from api.domain.source import Source
from api.domain.source_balance import SourceBalance
from api.enums import EntityStatus
from api.mappers.source_mapper import SourceMapper
from api.orm.record import RecordORM
from api.orm.source import SourceORM
from api.orm.source_association import SourceAssociationORM
from api.orm.transfer import TransferORM
from api.repositories.base import BaseRepository

# Ноль нужного типа. Без явного Numeric COALESCE с целочисленным литералом
# может вернуть не Decimal, и денежная арифметика поедет по типам.
_ZERO = literal(Decimal("0"), MONEY)


class SourceRepository(BaseRepository[SourceORM, Source]):
    """Доступ к счетам и расчёт их текущего баланса."""

    orm_type = SourceORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SourceMapper())

    async def list_by_spreadsheet(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Source]:
        """Возвращает счета документа, отсортированные по id."""
        stmt = select(SourceORM).where(SourceORM.spreadsheet_id == spreadsheet_id)
        if not include_deleted:
            stmt = stmt.where(SourceORM.deleted_at.is_(None))
        if only_active:
            stmt = stmt.where(SourceORM.status == EntityStatus.ACTIVE)
        rows = (await self._session.scalars(stmt.order_by(SourceORM.id))).all()
        return self._mapper.to_domain_list(rows)

    async def get_for_spreadsheet(
        self,
        source_id: int,
        spreadsheet_id: int,
        *,
        include_deleted: bool = False,
    ) -> Source | None:
        """Возвращает счёт, только если он принадлежит указанному документу."""
        stmt = select(SourceORM).where(
            SourceORM.id == source_id,
            SourceORM.spreadsheet_id == spreadsheet_id,
        )
        if not include_deleted:
            stmt = stmt.where(SourceORM.deleted_at.is_(None))
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def find_by_association(self, spreadsheet_id: int, alias: str) -> Source | None:
        """Находит живой счёт по псевдониму.

        Однозначность обеспечивает уникальный ключ дочерней таблицы, а не
        порядок перебора: прежняя реализация просматривала все счета и
        оставляла последнее совпадение, поэтому при дублирующемся псевдониме
        результат зависел от порядка строк.
        """
        stmt = (
            select(SourceORM)
            .join(SourceAssociationORM, SourceAssociationORM.source_id == SourceORM.id)
            .where(
                SourceORM.spreadsheet_id == spreadsheet_id,
                SourceAssociationORM.alias == alias.strip().lower(),
                SourceORM.deleted_at.is_(None),
            )
        )
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def replace_associations_bulk(
        self,
        by_source: Mapping[int, Iterable[str]],
    ) -> None:
        """Заменяет псевдонимы сразу у нескольких счетов одного документа.

        Уникальность псевдонима действует на весь документ, поэтому обмен
        псевдонимами между двумя счетами нельзя выполнить по одному: вставка
        первого упрётся в псевдоним, который второй ещё не отдал. Работает
        только общее удаление → `flush` → общая вставка.
        """
        if not by_source:
            return

        rows = (
            await self._session.scalars(select(SourceORM).where(SourceORM.id.in_(by_source)))
        ).all()
        spreadsheet_by_source = {orm.id: orm.spreadsheet_id for orm in rows}

        await self._session.execute(
            delete(SourceAssociationORM).where(SourceAssociationORM.source_id.in_(by_source))
        )
        await self._session.flush()

        self._session.add_all(
            [
                SourceAssociationORM(
                    spreadsheet_id=spreadsheet_by_source[source_id],
                    source_id=source_id,
                    alias=alias,
                )
                for source_id, aliases in by_source.items()
                if source_id in spreadsheet_by_source
                for alias in normalize_terms(aliases)
            ]
        )
        await self._session.flush()

    async def replace_associations(self, source_id: int, aliases: Iterable[str]) -> Source | None:
        """Заменяет набор псевдонимов счёта: удаляет все и вставляет заданные.

        `flush` между удалением и вставкой обязателен. Без него SQLAlchemy
        выдаёт `INSERT` раньше `DELETE` в пределах одного flush, и добавление
        псевдонима к существующему набору падает на уникальном ключе — старая
        строка с тем же значением ещё жива.
        """
        orm = await self._session.get(SourceORM, source_id)
        if orm is None:
            return None

        await self._session.execute(
            delete(SourceAssociationORM).where(SourceAssociationORM.source_id == source_id)
        )
        await self._session.flush()

        self._session.add_all(
            [
                SourceAssociationORM(
                    spreadsheet_id=orm.spreadsheet_id,
                    source_id=source_id,
                    alias=alias,
                )
                for alias in normalize_terms(aliases)
            ]
        )
        await self._session.flush()
        await self._session.refresh(orm)
        return self._mapper.to_domain(orm)

    async def balances(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
    ) -> list[SourceBalance]:
        """Считает текущие балансы живых счетов документа одним запросом.

        Баланс не хранится: он равен начальному балансу плюс операции, плюс
        входящие переводы, минус исходящие. Поэтому расхождение баланса с
        реестром — не редкое состояние, которое надо ловить, а невыразимое.

        Считается **тремя коррелированными подзапросами**, а не тремя `LEFT JOIN`
        с `GROUP BY`. Соединение перемножило бы строки: три операции, два
        входящих перевода и два исходящих дали бы двенадцать строк, и каждая
        сумма посчиталась бы кратно числу строк остальных таблиц.
        """
        stmt = select(
            SourceORM.id,
            SourceORM.title,
            SourceORM.start_balance,
            self._balance_expression().label("balance"),
        ).where(
            SourceORM.spreadsheet_id == spreadsheet_id,
            SourceORM.deleted_at.is_(None),
        )
        if only_active:
            stmt = stmt.where(SourceORM.status == EntityStatus.ACTIVE)

        rows = (await self._session.execute(stmt.order_by(SourceORM.id))).all()
        return [
            SourceBalance(
                source_id=row.id,
                title=row.title,
                start_balance=row.start_balance,
                balance=row.balance,
            )
            for row in rows
        ]

    async def balance_of(self, source_id: int) -> SourceBalance | None:
        """Считает баланс одного счёта."""
        stmt = select(
            SourceORM.id,
            SourceORM.title,
            SourceORM.start_balance,
            self._balance_expression().label("balance"),
        ).where(SourceORM.id == source_id)

        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return SourceBalance(
            source_id=row.id,
            title=row.title,
            start_balance=row.start_balance,
            balance=row.balance,
        )

    # --- Составные части агрегата баланса ---

    @classmethod
    def _balance_expression(cls) -> ColumnElement[Decimal]:
        """Начальный баланс + операции + входящие переводы − исходящие."""
        return (
            SourceORM.start_balance
            + cls._records_sum()
            + cls._transfers_sum(TransferORM.to_source_id)
            - cls._transfers_sum(TransferORM.from_source_id)
        )

    @staticmethod
    def _records_sum() -> ColumnElement[Decimal]:
        """Сумма операций счёта. Знаковая: расходы уже отрицательны."""
        return func.coalesce(
            select(func.sum(RecordORM.amount))
            .where(
                RecordORM.source_id == SourceORM.id,
                RecordORM.deleted_at.is_(None),
            )
            .correlate(SourceORM)
            .scalar_subquery(),
            _ZERO,
        )

    @staticmethod
    def _transfers_sum(side: InstrumentedAttribute[int]) -> ColumnElement[Decimal]:
        """Сумма переводов по одной стороне: `to_source_id` или `from_source_id`."""
        return func.coalesce(
            select(func.sum(TransferORM.amount))
            .where(
                side == SourceORM.id,
                TransferORM.deleted_at.is_(None),
            )
            .correlate(SourceORM)
            .scalar_subquery(),
            _ZERO,
        )
