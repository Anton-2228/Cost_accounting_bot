"""ORM-модель категории доходов или расходов."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core import constants
from api.db.base import Base
from api.db.column_types import CATEGORY_KIND, ENTITY_STATUS
from api.db.mixins import PkMixin, SoftDeleteMixin, TimestampMixin
from api.enums import CategoryKind, EntityStatus

if TYPE_CHECKING:
    from api.orm.category_association import CategoryAssociationORM
    from api.orm.category_product_type import CategoryProductTypeORM


class CategoryORM(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Категория операции.

    `kind` задаёт знак операции: доход прибавляется к балансу, расход
    вычитается. Знак — свойство категории, а не пользовательского ввода.

    Псевдонимы (по которым бот сопоставляет введённый текст с категорией) и типы
    товаров (по которым пайплайн чеков относит позицию к категории) живут в
    дочерних таблицах :class:`api.orm.category_association.CategoryAssociationORM`
    и :class:`api.orm.category_product_type.CategoryProductTypeORM`. Раньше это
    были массивы `TEXT[]`, и уникальность псевдонима не выражалась схемой вовсе:
    её проверял только Python при разборе листа, поэтому два одинаковых
    псевдонима, созданные разными запросами, спокойно уживались, а подбор молча
    возвращал последнее совпадение.

    Уникальность названия — **частичный** уникальный индекс по `lower(title)`
    среди живых строк. Составной он потому, что название должно быть уникально
    внутри документа, а не глобально; частичный — чтобы удалённая категория не
    блокировала создание одноимённой заново; по `lower(...)` — потому что подбор
    работает в нижнем регистре, и «Еда» с «еда» иначе стали бы разными строками
    с одинаковым псевдонимом.
    """

    __tablename__ = "categories"
    __table_args__ = (
        # Нужен для составных внешних ключей из records и дочерних таблиц —
        # см. пояснение в api/orm/period.py.
        UniqueConstraint("id", "spreadsheet_id", name="uq_categories_id_spreadsheet_id"),
        Index(
            "ix_categories_title_alive",
            "spreadsheet_id",
            text("lower(title)"),
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        # Чтение справочника для листа Categories.
        Index(
            "ix_categories_spreadsheet_id_alive",
            "spreadsheet_id",
            "id",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[CategoryKind] = mapped_column(CATEGORY_KIND, nullable=False)
    status: Mapped[EntityStatus] = mapped_column(
        ENTITY_STATUS,
        nullable=False,
        server_default=EntityStatus.ACTIVE.value,
    )
    title: Mapped[str] = mapped_column(String(constants.TITLE_MAX_LENGTH), nullable=False)

    # lazy="selectin" — единственный безопасный вариант в async. Обычная ленивая
    # загрузка сработала бы при обращении к атрибуту, то есть там, где негде
    # поставить await, и упала бы с MissingGreenlet. selectin догружает детей
    # отдельным запросом сразу после основного, одним разом на всю выборку.
    association_rows: Mapped[list[CategoryAssociationORM]] = relationship(
        "CategoryAssociationORM",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="CategoryAssociationORM.alias",
    )
    product_type_rows: Mapped[list[CategoryProductTypeORM]] = relationship(
        "CategoryProductTypeORM",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="CategoryProductTypeORM.product_type",
    )
