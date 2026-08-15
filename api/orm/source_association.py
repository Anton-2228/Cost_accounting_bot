"""ORM-модель псевдонима источника денег."""

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


class SourceAssociationORM(PkMixin, TimestampMixin, Base):
    """Слово, по которому пользовательский ввод сопоставляется со счётом.

    Пространство имён у счетов своё: `UNIQUE (spreadsheet_id, alias)` действует
    внутри этой таблицы, поэтому один и тот же псевдоним у категории и у счёта
    не конфликтует. Это не упущение — в команде вида
    ``/add 500 продукты карта`` позиция аргумента однозначно говорит, что́
    подбирается, и совпадение слов неоднозначности не создаёт.
    """

    __tablename__ = "source_associations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "spreadsheet_id"],
            ["sources.id", "sources.spreadsheet_id"],
            ondelete="CASCADE",
            name="fk_source_associations_source_id_sources",
        ),
        UniqueConstraint(
            "spreadsheet_id",
            "alias",
            name="uq_source_associations_spreadsheet_id_alias",
        ),
        CheckConstraint("alias = lower(alias)", name="alias_lowercase"),
        CheckConstraint("length(alias) > 0", name="alias_not_empty"),
        Index("ix_source_associations_source_id", "source_id"),
    )

    spreadsheet_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    alias: Mapped[str] = mapped_column(String(constants.TITLE_MAX_LENGTH), nullable=False)
