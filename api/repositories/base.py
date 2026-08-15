"""Базовый репозиторий: CRUD, пагинация и хуки для фильтров и join'ов.

Репозиторий принимает и возвращает доменные модели; конвертация ORM ↔ domain
выполняется маппером. ORM-объекты не покидают этот слой.

Транзакцией управляет сервисный слой — здесь только `flush`/`refresh`. Одна
пользовательская операция это несколько записей в разные таблицы плюс строка в
очереди перерисовки листов, и попасть в БД они должны целиком или никак.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, Result, Select, func, not_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.base import Base
from api.mappers.base import BaseMapper

# Поля, которыми управляет БД, — их нельзя перезаписывать при обновлении.
_IMMUTABLE_COLUMNS = frozenset({"id", "created_at", "updated_at"})


def affected_rows(result: Result[Any]) -> int:
    """Число строк, затронутых DML-оператором.

    `session.execute()` типизирован как `Result`, а `rowcount` объявлен на
    `CursorResult`, который и возвращается для INSERT/UPDATE/DELETE. Приведение
    собрано в одном месте, чтобы не расползаться по репозиториям.
    """
    return cast("CursorResult[Any]", result).rowcount


class BaseRepository[ORM_T: Base, DOMAIN_T]:
    """Обобщённый репозиторий доступа к данным для одной сущности."""

    orm_type: type[ORM_T]

    def __init__(self, session: AsyncSession, mapper: BaseMapper[ORM_T, DOMAIN_T]) -> None:
        self._session = session
        self._mapper = mapper

    async def get_by_id(self, entity_id: int, *, include_deleted: bool = False) -> DOMAIN_T | None:
        """Возвращает доменную модель по id или None.

        Мягко удалённая запись вернётся только при `include_deleted=True`.
        """
        orm = await self._session.get(self.orm_type, entity_id)
        if orm is None:
            return None
        if not include_deleted and self._is_deleted(orm):
            return None
        return self._mapper.to_domain(orm)

    async def list(self, limit: int, offset: int, **filters: Any) -> tuple[list[DOMAIN_T], int]:
        """Возвращает страницу доменных моделей и общее число записей под фильтр."""
        include_deleted = bool(filters.pop("include_deleted", False))
        conditions = list(self._build_conditions(filters))

        deleted_filter = self._deleted_filter()
        if deleted_filter is not None and not include_deleted:
            conditions.append(not_(deleted_filter))

        stmt: Select[Any] = self._apply_joins(select(self.orm_type))
        count_stmt: Select[Any] = self._apply_joins(
            select(func.count()).select_from(self.orm_type)
        )
        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)

        stmt = stmt.order_by(*self.orm_type.__table__.primary_key).limit(limit).offset(offset)

        rows = (await self._session.scalars(stmt)).all()
        total = await self._session.scalar(count_stmt) or 0
        return self._mapper.to_domain_list(rows), int(total)

    async def add(self, domain: DOMAIN_T) -> DOMAIN_T:
        """Вставляет запись и возвращает её с заполненными БД полями.

        `flush` + `refresh` обязательны: до них у объекта нет ни `id`, ни
        серверных значений по умолчанию, и наружу уехала бы доменная модель с
        `None` в полях, которые в БД заполнены.
        """
        orm = self._mapper.to_orm(domain)
        self._session.add(orm)
        await self._session.flush()
        await self._session.refresh(orm)
        return self._mapper.to_domain(orm)

    async def update(self, domain: DOMAIN_T) -> DOMAIN_T | None:
        """Обновляет запись по id доменной модели; None, если записи нет."""
        entity_id = getattr(domain, "id", None)
        if entity_id is None:
            raise ValueError("Для обновления требуется id доменной модели")

        existing = await self._session.get(self.orm_type, entity_id)
        if existing is None:
            return None

        source = self._mapper.to_orm(domain)
        for column in self.orm_type.__table__.columns:
            if column.key in _IMMUTABLE_COLUMNS:
                continue
            setattr(existing, column.key, getattr(source, column.key))

        await self._session.flush()
        await self._session.refresh(existing)
        return self._mapper.to_domain(existing)

    async def soft_delete(self, entity_id: int, *, at: datetime) -> bool:
        """Помечает запись удалённой; True, если она была жива.

        Условие `deleted_at IS NULL` обязательно и не является перестраховкой:
        без него повторный вызов переписал бы метку времени и исказил
        хронологию, а метод сообщил бы об успехе там, где ничего не изменилось.
        """
        if not hasattr(self.orm_type, "deleted_at"):
            raise NotImplementedError(
                f"{self.orm_type.__name__} не поддерживает мягкое удаление"
            )

        stmt = (
            update(self.orm_type)
            .where(
                self.orm_type.id == entity_id,  # type: ignore[attr-defined]
                self.orm_type.deleted_at.is_(None),  # type: ignore[attr-defined]
            )
            .values(deleted_at=at)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return bool(affected_rows(result))

    async def delete(self, entity_id: int) -> bool:
        """Физически удаляет запись; True, если она существовала."""
        existing = await self._session.get(self.orm_type, entity_id)
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    # --- Хуки для переопределения в конкретных репозиториях ---

    def _apply_joins(self, stmt: Select[Any]) -> Select[Any]:
        """Добавляет join'ы к запросам list/count (по умолчанию — без join'ов)."""
        return stmt

    def _build_conditions(self, filters: Mapping[str, Any]) -> Sequence[ColumnElement[bool]]:
        """Собирает условия фильтрации из переданных параметров."""
        return []

    def _deleted_filter(self) -> ColumnElement[bool] | None:
        """Условие «запись мягко удалена» или None, если удаление физическое.

        Определяется автоматически по наличию колонки `deleted_at`, поэтому
        конкретным репозиториям переопределять его не нужно.
        """
        deleted_at = getattr(self.orm_type, "deleted_at", None)
        if deleted_at is None:
            return None
        return deleted_at.is_not(None)

    def _is_deleted(self, orm: ORM_T) -> bool:
        """Проверяет, помечен ли загруженный ORM-объект удалённым."""
        return getattr(orm, "deleted_at", None) is not None

    def _alive(self) -> Sequence[ColumnElement[bool]]:
        """Условие «запись жива» для точечных запросов конкретных репозиториев."""
        deleted_filter = self._deleted_filter()
        return () if deleted_filter is None else (not_(deleted_filter),)
