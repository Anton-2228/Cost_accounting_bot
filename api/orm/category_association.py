"""ORM-модель псевдонима категории."""

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


class CategoryAssociationORM(PkMixin, TimestampMixin, Base):
    """Слово, по которому пользовательский ввод сопоставляется с категорией.

    `UNIQUE (spreadsheet_id, alias)` — то, ради чего псевдонимы вынесены из
    массива в таблицу: неоднозначный подбор становится невозможным состоянием, а
    не тем, что должен не забыть проверить сервис.

    Псевдоним хранится уже нормализованным (нижний регистр, без пробелов по
    краям); `CHECK` не даёт положить ненормализованное значение в обход сервиса.

    Порядок при чтении задаётся `ORDER BY alias`. Раньше набор дедуплицировался
    через `set()`, а хеш строк в Python рандомизирован при каждом запуске
    процесса, поэтому лист `Categories` перетасовывался при каждой синхронизации
    и пользователь не мог понять, изменилось что-нибудь или нет.
    """

    __tablename__ = "category_associations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["category_id", "spreadsheet_id"],
            ["categories.id", "categories.spreadsheet_id"],
            ondelete="CASCADE",
            name="fk_category_associations_category_id_categories",
        ),
        UniqueConstraint(
            "spreadsheet_id",
            "alias",
            name="uq_category_associations_spreadsheet_id_alias",
        ),
        CheckConstraint("alias = lower(alias)", name="alias_lowercase"),
        CheckConstraint("length(alias) > 0", name="alias_not_empty"),
        Index("ix_category_associations_category_id", "category_id"),
    )

    spreadsheet_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    alias: Mapped[str] = mapped_column(String(constants.TITLE_MAX_LENGTH), nullable=False)
