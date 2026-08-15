"""Репозиторий категорий."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.text import normalize_terms
from api.domain.category import Category
from api.enums import EntityStatus
from api.mappers.category_mapper import CategoryMapper
from api.orm.category import CategoryORM
from api.orm.category_association import CategoryAssociationORM
from api.orm.category_product_type import CategoryProductTypeORM
from api.repositories.base import BaseRepository


class CategoryRepository(BaseRepository[CategoryORM, Category]):
    """Доступ к категориям вместе с псевдонимами и типами товаров."""

    orm_type = CategoryORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CategoryMapper())

    async def list_by_spreadsheet(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Category]:
        """Возвращает категории документа, отсортированные по id."""
        stmt = select(CategoryORM).where(CategoryORM.spreadsheet_id == spreadsheet_id)
        if not include_deleted:
            stmt = stmt.where(CategoryORM.deleted_at.is_(None))
        if only_active:
            stmt = stmt.where(CategoryORM.status == EntityStatus.ACTIVE)
        rows = (await self._session.scalars(stmt.order_by(CategoryORM.id))).all()
        return self._mapper.to_domain_list(rows)

    async def get_for_spreadsheet(
        self,
        category_id: int,
        spreadsheet_id: int,
        *,
        include_deleted: bool = False,
    ) -> Category | None:
        """Возвращает категорию, только если она принадлежит указанному документу."""
        stmt = select(CategoryORM).where(
            CategoryORM.id == category_id,
            CategoryORM.spreadsheet_id == spreadsheet_id,
        )
        if not include_deleted:
            stmt = stmt.where(CategoryORM.deleted_at.is_(None))
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def find_by_association(self, spreadsheet_id: int, alias: str) -> Category | None:
        """Находит живую категорию по псевдониму.

        Однозначность обеспечивает уникальный ключ дочерней таблицы. Прежняя
        реализация перебирала все категории и оставляла последнее совпадение,
        поэтому при дублирующемся псевдониме результат зависел от порядка строк.
        """
        stmt = (
            select(CategoryORM)
            .join(CategoryAssociationORM, CategoryAssociationORM.category_id == CategoryORM.id)
            .where(
                CategoryORM.spreadsheet_id == spreadsheet_id,
                CategoryAssociationORM.alias == alias.strip().lower(),
                CategoryORM.deleted_at.is_(None),
            )
        )
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def find_by_product_type(self, spreadsheet_id: int, product_type: str) -> Category | None:
        """Находит живую категорию, к которой отнесён тип товара."""
        stmt = (
            select(CategoryORM)
            .join(CategoryProductTypeORM, CategoryProductTypeORM.category_id == CategoryORM.id)
            .where(
                CategoryORM.spreadsheet_id == spreadsheet_id,
                CategoryProductTypeORM.product_type == product_type.strip().lower(),
                CategoryORM.deleted_at.is_(None),
            )
        )
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def replace_associations(
        self,
        category_id: int,
        aliases: Iterable[str],
    ) -> Category | None:
        """Заменяет набор псевдонимов категории.

        `flush` между удалением и вставкой обязателен: SQLAlchemy в пределах
        одного flush выдаёт `INSERT` раньше `DELETE`, и добавление псевдонима к
        существующему набору упало бы на уникальном ключе.
        """
        orm = await self._session.get(CategoryORM, category_id)
        if orm is None:
            return None

        await self._session.execute(
            delete(CategoryAssociationORM).where(
                CategoryAssociationORM.category_id == category_id
            )
        )
        await self._session.flush()

        self._session.add_all(
            [
                CategoryAssociationORM(
                    spreadsheet_id=orm.spreadsheet_id,
                    category_id=category_id,
                    alias=alias,
                )
                for alias in normalize_terms(aliases)
            ]
        )
        await self._session.flush()
        await self._session.refresh(orm)
        return self._mapper.to_domain(orm)

    async def replace_associations_bulk(
        self,
        by_category: Mapping[int, Iterable[str]],
    ) -> None:
        """Заменяет псевдонимы сразу у нескольких категорий одного документа.

        Нужно там, где набор правится целиком по листу. Уникальность псевдонима
        действует на весь документ, а не на категорию, поэтому обмен
        псевдонимами между двумя категориями невозможно выполнить по одной:
        вставка первой упрётся в псевдоним, который вторая ещё не отдала.
        Единственный порядок, который работает, — снять **все** старые наборы,
        сделать `flush`, и только потом вставлять новые.
        """
        if not by_category:
            return

        rows = (
            await self._session.scalars(
                select(CategoryORM).where(CategoryORM.id.in_(by_category))
            )
        ).all()
        spreadsheet_by_category = {orm.id: orm.spreadsheet_id for orm in rows}

        await self._session.execute(
            delete(CategoryAssociationORM).where(
                CategoryAssociationORM.category_id.in_(by_category)
            )
        )
        await self._session.flush()

        self._session.add_all(
            [
                CategoryAssociationORM(
                    spreadsheet_id=spreadsheet_by_category[category_id],
                    category_id=category_id,
                    alias=alias,
                )
                for category_id, aliases in by_category.items()
                if category_id in spreadsheet_by_category
                for alias in normalize_terms(aliases)
            ]
        )
        await self._session.flush()

    async def replace_product_types_bulk(
        self,
        by_category: Mapping[int, Iterable[str]],
    ) -> None:
        """Заменяет типы товаров сразу у нескольких категорий одного документа.

        Та же причина, что и у :meth:`replace_associations_bulk`: тип товара
        уникален в пределах документа, поэтому переезд типа из одной категории
        в другую требует общего удаления перед вставкой.
        """
        if not by_category:
            return

        rows = (
            await self._session.scalars(
                select(CategoryORM).where(CategoryORM.id.in_(by_category))
            )
        ).all()
        spreadsheet_by_category = {orm.id: orm.spreadsheet_id for orm in rows}

        await self._session.execute(
            delete(CategoryProductTypeORM).where(
                CategoryProductTypeORM.category_id.in_(by_category)
            )
        )
        await self._session.flush()

        self._session.add_all(
            [
                CategoryProductTypeORM(
                    spreadsheet_id=spreadsheet_by_category[category_id],
                    category_id=category_id,
                    product_type=product_type,
                )
                for category_id, product_types in by_category.items()
                if category_id in spreadsheet_by_category
                for product_type in normalize_terms(product_types)
            ]
        )
        await self._session.flush()

    async def replace_product_types(
        self,
        category_id: int,
        product_types: Iterable[str],
    ) -> Category | None:
        """Заменяет набор типов товаров категории."""
        orm = await self._session.get(CategoryORM, category_id)
        if orm is None:
            return None

        await self._session.execute(
            delete(CategoryProductTypeORM).where(
                CategoryProductTypeORM.category_id == category_id
            )
        )
        await self._session.flush()

        self._session.add_all(
            [
                CategoryProductTypeORM(
                    spreadsheet_id=orm.spreadsheet_id,
                    category_id=category_id,
                    product_type=product_type,
                )
                for product_type in normalize_terms(product_types)
            ]
        )
        await self._session.flush()
        await self._session.refresh(orm)
        return self._mapper.to_domain(orm)

    async def add_product_type(self, category_id: int, product_type: str) -> Category | None:
        """Добавляет один тип товара, если его ещё нет у этой категории.

        Если тип уже занят другой категорией документа, вставка нарушит
        уникальный ключ — и это правильно: молчаливое переназначение сделало бы
        раскладку позиций чека зависящей от порядка обработки.
        """
        orm = await self._session.get(CategoryORM, category_id)
        if orm is None:
            return None

        normalized = normalize_terms([product_type])
        if not normalized:
            return self._mapper.to_domain(orm)

        value = normalized[0]
        if value not in {row.product_type for row in orm.product_type_rows}:
            self._session.add(
                CategoryProductTypeORM(
                    spreadsheet_id=orm.spreadsheet_id,
                    category_id=category_id,
                    product_type=value,
                )
            )
            await self._session.flush()
            await self._session.refresh(orm)
        return self._mapper.to_domain(orm)
