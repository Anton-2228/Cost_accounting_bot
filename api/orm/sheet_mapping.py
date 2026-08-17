"""ORM-модель соответствия «адресат перерисовки → лист Google-документа»."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.core import constants
from api.db.base import Base
from api.db.column_types import SHEET_TARGET
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import SheetTarget


class SheetMappingORM(PkMixin, TimestampMixin, Base):
    """Где физически лежит лист: его числовой `sheetId` и заголовок в документе.

    Благодаря этой таблице `google_sheets_service` остаётся stateless, а api
    знает, готовы ли листы периода: ролловер отвечает на вопрос «лист уже
    создан?» запросом к БД, а не походом в Google.

    В старой версии соответствия не существовало вовсе — единственным знанием
    было соглашение «заголовок листа операций равен `str(start_date)`».
    Диапазоны собирались форматированием строки, а числовой `sheetId` каждый раз
    искался перебором всех листов документа. Как только ролловер сдвигал
    `start_date` в БД, но падал на создании листа, все последующие обращения
    строили диапазон по несуществующему заголовку — и документ ломался
    безвозвратно.

    Наличие строки означает «лист создан», поэтому запись появляется **после**
    подтверждения от Google, а не до.
    """

    __tablename__ = "sheet_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["period_id", "spreadsheet_id"],
            ["periods.id", "periods.spreadsheet_id"],
            ondelete="CASCADE",
            name="fk_sheet_mappings_period_id_periods",
        ),
        UniqueConstraint(
            "spreadsheet_id",
            "target",
            "period_id",
            name="uq_sheet_mappings_key",
            postgresql_nulls_not_distinct=True,
        ),
        # Один лист документа не может быть занят двумя адресатами.
        UniqueConstraint(
            "spreadsheet_id",
            "google_sheet_id",
            name="uq_sheet_mappings_spreadsheet_id_google_sheet_id",
        ),
        CheckConstraint(
            "(target IN ('OPERATIONS', 'STATISTICS', 'CHECKS')) = (period_id IS NOT NULL)",
            name="period_matches_target",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    target: Mapped[SheetTarget] = mapped_column(SHEET_TARGET, nullable=False)
    period_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    #: Числовой идентификатор листа внутри документа (`sheetId` в Sheets API).
    google_sheet_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(
        String(constants.GOOGLE_SHEET_TITLE_MAX_LENGTH),
        nullable=False,
    )
