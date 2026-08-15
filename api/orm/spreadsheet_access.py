"""ORM-модель выданного доступа к Google-документу."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.core import constants
from api.db.base import Base
from api.db.column_types import ACCESS_ROLE
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import AccessRole


class SpreadsheetAccessORM(PkMixin, TimestampMixin, Base):
    """Почта, которой открыт доступ к документу.

    Заменяет массив `gmail` из старой схемы. Массив не позволял отличить
    «доступ записан» от «доступ реально выдан в Google»: строка добавлялась до
    вызова Drive API, и при его сбое почта навсегда оставалась в списке без
    фактического доступа. Здесь это разные состояния — `granted_at IS NULL`
    означает «выдать ещё предстоит», и запись остаётся видимой работой для
    `google_sheets_service`.
    """

    __tablename__ = "spreadsheet_accesses"
    __table_args__ = (
        # Одной почте — один доступ к документу.
        UniqueConstraint(
            "spreadsheet_id",
            "email",
            name="uq_spreadsheet_accesses_spreadsheet_id_email",
        ),
        # Выборка «что ещё предстоит выдать»: индекс покрывает только
        # невыданные доступы, поэтому не растёт вместе с историей.
        Index(
            "ix_spreadsheet_accesses_pending",
            "spreadsheet_id",
            postgresql_where="granted_at IS NULL",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(constants.EMAIL_MAX_LENGTH), nullable=False)
    role: Mapped[AccessRole] = mapped_column(
        ACCESS_ROLE,
        nullable=False,
        server_default=AccessRole.WRITER.value,
    )
    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
