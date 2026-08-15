"""ORM-модель выученного соответствия «название товара → тип»."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.core import constants
from api.db.base import Base
from api.db.mixins import PkMixin, TimestampMixin


class CashedRecordORM(PkMixin, TimestampMixin, Base):
    """Кэш соответствий, позволяющий не спрашивать модель об уже знакомых товарах.

    Уникальность — `(spreadsheet_id, product_name)`. В старой схеме
    `product_name` был уникален **глобально**, поэтому первый же пользователь,
    закэшировавший «молоко», навсегда ломал кэширование этого слова всем
    остальным: вставка падала с нарушением уникальности, ошибка глушилась в
    savepoint, и каждый следующий чек снова требовал ручной классификации без
    единого объяснения пользователю.
    """

    __tablename__ = "cashed_records"
    __table_args__ = (
        UniqueConstraint(
            "spreadsheet_id",
            "product_name",
            name="uq_cashed_records_spreadsheet_id_product_name",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_name: Mapped[str] = mapped_column(
        String(constants.PRODUCT_NAME_MAX_LENGTH),
        nullable=False,
    )
    product_type: Mapped[str] = mapped_column(
        String(constants.PRODUCT_TYPE_MAX_LENGTH),
        nullable=False,
    )
