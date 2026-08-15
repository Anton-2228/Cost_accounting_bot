"""ORM-модель перевода между счетами."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.core import constants
from api.db.base import Base
from api.db.column_types import MONEY
from api.db.mixins import PkMixin, SoftDeleteMixin, TimestampMixin


class TransferORM(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Перемещение денег между двумя счетами одного документа.

    Отдельная сущность, а не пара записей в реестре, по существу предметной
    области: перевод **не является ни доходом, ни расходом**. Строкой в
    `records` он потребовал бы категорию и немедленно попал бы в «Общие доходы»
    или «Общие расходы», исказив отчёт.

    В старой версии перевод вообще не оставлял следа — двигались только балансы
    двух счетов. Ошибочный перевод нельзя было ни отменить (удаление работало
    только по `records`), ни объяснить, почему сумма по счетам перестала биться
    с листом операций.

    `amount` строго положительна, направление задают `from_source_id` и
    `to_source_id`. Прежняя схема принимала знак от пользователя, и
    ``/transfer -1000 А Б`` тихо переводил деньги в обратную сторону.
    """

    __tablename__ = "transfers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["period_id", "spreadsheet_id"],
            ["periods.id", "periods.spreadsheet_id"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_transfers_period_id_periods",
        ),
        ForeignKeyConstraint(
            ["from_source_id", "spreadsheet_id"],
            ["sources.id", "sources.spreadsheet_id"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_transfers_from_source_id_sources",
        ),
        ForeignKeyConstraint(
            ["to_source_id", "spreadsheet_id"],
            ["sources.id", "sources.spreadsheet_id"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_transfers_to_source_id_sources",
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("from_source_id <> to_source_id", name="sources_differ"),
        Index(
            "ix_transfers_period_id_alive",
            "period_id",
            "id",
            postgresql_where="deleted_at IS NULL",
        ),
        # Обе стороны участвуют в агрегате баланса, поэтому индексов два.
        Index(
            "ix_transfers_from_source_id_alive",
            "from_source_id",
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_transfers_to_source_id_alive",
            "to_source_id",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    from_source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    added_at: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str] = mapped_column(
        String(constants.NOTES_MAX_LENGTH),
        nullable=False,
        server_default=text("''"),
    )
