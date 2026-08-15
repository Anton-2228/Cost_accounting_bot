"""ORM-модель типа товара, отнесённого к категории."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.core import constants
from api.db.base import Base
from api.db.mixins import PkMixin, TimestampMixin


class CategoryProductTypeORM(PkMixin, TimestampMixin, Base):
    """Тип товара, по которому позиция чека попадает в категорию.

    `UNIQUE (spreadsheet_id, product_type)` гарантирует, что один тип товара не
    может быть заявлен двумя категориями сразу: иначе позиция чека
    раскладывалась бы в ту или другую в зависимости от порядка строк.
    """

    __tablename__ = "category_product_types"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "spreadsheet_id"],
            ["categories.id", "categories.spreadsheet_id"],
            ondelete="CASCADE",
            name="fk_category_product_types_category_id_categories",
        ),
        UniqueConstraint(
            "spreadsheet_id",
            "product_type",
            name="uq_category_product_types_spreadsheet_id_product_type",
        ),
        CheckConstraint("product_type = lower(product_type)", name="product_type_lowercase"),
        CheckConstraint("length(product_type) > 0", name="product_type_not_empty"),
        Index("ix_category_product_types_category_id", "category_id"),
    )

    spreadsheet_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_type: Mapped[str] = mapped_column(
        String(constants.PRODUCT_TYPE_MAX_LENGTH),
        nullable=False,
    )
