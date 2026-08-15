"""ORM-модель необработанного чека в очереди."""

from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.mixins import PkMixin, TimestampMixin


class CheckQueueItemORM(PkMixin, TimestampMixin, Base):
    """Сырой текст чека, ожидающий разбора.

    Очередь наполняется извне и разбирается ботом по одному чеку за раз.
    Порядок обработки — по `id`, то есть по времени поступления.
    """

    __tablename__ = "check_queue_items"
    __table_args__ = (Index("ix_check_queue_items_spreadsheet_id", "spreadsheet_id", "id"),)

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    check_text: Mapped[str] = mapped_column(Text, nullable=False)
