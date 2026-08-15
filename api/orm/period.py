"""ORM-модель учётного периода."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import PERIOD_STATUS
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import PeriodStatus


class PeriodORM(PkMixin, TimestampMixin, Base):
    """Учётный «месяц» одной таблицы: полуинтервал ``[start_date, end_date)``.

    Период — строка в БД, а не подвижный указатель `start_date` в таблице
    документа, как было раньше. Это даёт три вещи, которых не хватало:

    * `UNIQUE (spreadsheet_id, start_date)` делает создание периода
      идемпотентным (`ON CONFLICT DO NOTHING`), поэтому ролловер можно
      повторять сколько угодно раз и догонять любое число пропущенных месяцев.
      Старый ролловер срабатывал только при точном равенстве `today == end_date`
      и терял месяц безвозвратно, если сервис в этот день не работал.
    * Принадлежность операции месяцу становится внешним ключом, а не
      арифметикой по дате, — операция не может оказаться сразу в двух периодах.
    * Закрытие периода — отдельный факт с меткой времени, а не побочный эффект
      сдвига указателя.

    `end_date` **исключительный**: операция, датированная этим днём, относится
    уже к следующему периоду.
    """

    __tablename__ = "periods"
    __table_args__ = (
        UniqueConstraint(
            "spreadsheet_id",
            "start_date",
            name="uq_periods_spreadsheet_id_start_date",
        ),
        # Данные это не ограничивает: id уже первичный ключ, поэтому пара
        # (id, spreadsheet_id) уникальна сама по себе. Констрейнт нужен, чтобы
        # стал возможен составной внешний ключ из records/transfers/sheet_*:
        # PostgreSQL требует UNIQUE ровно по тому набору колонок, на который
        # ссылается FK. Взамен получаем гарантию на уровне БД, что операция и её
        # период принадлежат одному документу.
        UniqueConstraint("id", "spreadsheet_id", name="uq_periods_id_spreadsheet_id"),
        CheckConstraint("end_date > start_date", name="dates_order"),
        # Поиск незакрытых периодов при ролловере.
        Index(
            "ix_periods_open",
            "spreadsheet_id",
            postgresql_where="status = 'OPEN'",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PeriodStatus] = mapped_column(
        PERIOD_STATUS,
        nullable=False,
        server_default=PeriodStatus.OPEN.value,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
