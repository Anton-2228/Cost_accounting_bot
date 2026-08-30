"""ORM-модель источника денег (счёта)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.core import constants
from api.db.base import Base
from api.db.column_types import CURRENCY, ENTITY_STATUS, MONEY
from api.db.mixins import PkMixin, SoftDeleteMixin, TimestampMixin
from api.enums import Currency, EntityStatus

if TYPE_CHECKING:
    from api.orm.source_association import SourceAssociationORM


class SourceORM(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Счёт, с которого уходят и на который приходят деньги.

    Хранится только `start_balance` — сумма, с которой счёт начал жизнь.
    **Колонки `current_balance` нет намеренно.** В старой схеме она была
    `DOUBLE PRECISION` и правилась инкрементально
    (``SET current_balance = current_balance + :shift``) при каждой операции.
    Такой баланс расходится с реестром при любом сбое или гонке, и обнаружить
    расхождение нечем: сравнивать не с чем.

    Текущий баланс считается агрегатом от начального баланса, операций и
    переводов — см.
    :meth:`api.repositories.source_repository.SourceRepository.balances`.
    Расхождение с реестром при этом не существует как состояние.

    Псевдонимы вынесены в :class:`api.orm.source_association.SourceAssociationORM`
    по тем же причинам, что и у категорий.
    """

    __tablename__ = "sources"
    __table_args__ = (
        # Нужен для составных внешних ключей из records/transfers и дочерней
        # таблицы псевдонимов — см. пояснение в api/orm/period.py.
        UniqueConstraint("id", "spreadsheet_id", name="uq_sources_id_spreadsheet_id"),
        Index(
            "ix_sources_title_alive",
            "spreadsheet_id",
            text("lower(title)"),
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_sources_spreadsheet_id_alive",
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
    status: Mapped[EntityStatus] = mapped_column(
        ENTITY_STATUS,
        nullable=False,
        server_default=EntityStatus.ACTIVE.value,
    )
    title: Mapped[str] = mapped_column(String(constants.TITLE_MAX_LENGTH), nullable=False)
    # Валюта счёта. Без `server_default`: значение приходит из листа `Bills` и
    # проверяется на импорте, поэтому «валюта по умолчанию» существовала бы
    # ровно для того, чтобы молча подставиться вместо опечатки.
    currency: Mapped[Currency] = mapped_column(CURRENCY, nullable=False)
    start_balance: Mapped[Decimal] = mapped_column(
        MONEY,
        nullable=False,
        server_default=text("0"),
    )

    # lazy="selectin" — см. пояснение в api/orm/category.py.
    association_rows: Mapped[list[SourceAssociationORM]] = relationship(
        "SourceAssociationORM",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="SourceAssociationORM.alias",
    )
