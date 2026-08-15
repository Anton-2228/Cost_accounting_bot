"""Маппер категории."""

from __future__ import annotations

from api.domain.category import Category
from api.mappers.base import BaseMapper
from api.orm.category import CategoryORM
from api.orm.category_association import CategoryAssociationORM
from api.orm.category_product_type import CategoryProductTypeORM


class CategoryMapper(BaseMapper[CategoryORM, Category]):
    """Категория вместе с дочерними псевдонимами и типами товаров.

    В домене это плоские списки строк, в БД — отдельные таблицы с уникальностью
    в пределах документа. Сборкой и разборкой занимается маппер, поэтому
    сервисный слой о дочерних таблицах не знает.
    """

    def to_domain(self, orm: CategoryORM) -> Category:
        """Преобразует ORM-объект в доменную модель."""
        return Category(
            id=orm.id,
            spreadsheet_id=orm.spreadsheet_id,
            kind=orm.kind,
            status=orm.status,
            title=orm.title,
            associations=[row.alias for row in orm.association_rows],
            product_types=[row.product_type for row in orm.product_type_rows],
            deleted_at=orm.deleted_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def to_orm(self, domain: Category) -> CategoryORM:
        """Создаёт ORM-объект вместе с дочерними строками."""
        return CategoryORM(
            spreadsheet_id=domain.spreadsheet_id,
            kind=domain.kind,
            status=domain.status,
            title=domain.title,
            deleted_at=domain.deleted_at,
            association_rows=self.association_rows(domain),
            product_type_rows=self.product_type_rows(domain),
        )

    @staticmethod
    def association_rows(domain: Category) -> list[CategoryAssociationORM]:
        """Строит дочерние строки псевдонимов (без `category_id` — его проставит ORM)."""
        return [
            CategoryAssociationORM(spreadsheet_id=domain.spreadsheet_id, alias=alias)
            for alias in domain.associations
        ]

    @staticmethod
    def product_type_rows(domain: Category) -> list[CategoryProductTypeORM]:
        """Строит дочерние строки типов товаров."""
        return [
            CategoryProductTypeORM(
                spreadsheet_id=domain.spreadsheet_id,
                product_type=product_type,
            )
            for product_type in domain.product_types
        ]
