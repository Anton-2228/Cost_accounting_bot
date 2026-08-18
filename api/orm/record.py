"""ORM-модель операции (записи реестра)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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


class RecordORM(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Одна операция: расход или доход по конкретному счёту.

    `amount` **знаковая**: расход отрицателен, доход положителен. Знак ставит
    сервис по виду категории, пользователь его не задаёт. Тип — `NUMERIC(14,2)`,
    а не `DOUBLE PRECISION`, как было раньше: на float сумма трёх покупок по
    10.50 переставала совпадать с их суммой в отчёте, а инкрементальный баланс
    накапливал дрейф без всякой возможности его заметить.

    `added_at` — дата в часовом поясе владельца документа; её вычисляет код, а
    не `server_default`. Прежний `TIMEZONE('utc-3', now())` при контейнере в UTC
    давал операциям, введённым поздно вечером, дату следующего дня.

    Связи с периодом, категорией и счётом — **составные** внешние ключи,
    включающие `spreadsheet_id`. Поэтому сослаться на категорию из чужого
    документа физически нельзя; раньше это проверялось руками в каждом сервисе.
    Ключи отложенные (`DEFERRABLE INITIALLY DEFERRED`): при удалении документа
    Postgres каскадно удаляет и операции, и справочники, а порядок между
    каскадами не определён — отложенная проверка выполняется один раз в конце
    транзакции, когда удалено уже всё.

    Поля `product_name`, `product_type` и `check_id` заполняются только для
    позиций, распознанных из чека. `check_id` заменил прежний `check_json`:
    копия расшифровки лежала в каждой позиции чека целиком, хотя сам чек уже
    хранится строкой в `checks`. Ключ отложенный по той же причине, что и
    остальные: при удалении документа порядок каскадов не определён. `ondelete`
    не ставится за ненадобностью: чек не удаляется физически никогда — его
    удаление такое же мягкое, как у операции, — и повиснуть ссылке не на чем.

    Ограничения «сумма не ноль» на таблице нет. Нулевая позиция чека законна:
    акция «второй товар бесплатно» даёт строку с ценой 0, и отбросить её
    значило бы разойтись с итогом чека, а записать под видом ненулевой —
    исказить реестр.
    """

    __tablename__ = "records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["period_id", "spreadsheet_id"],
            ["periods.id", "periods.spreadsheet_id"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_records_period_id_periods",
        ),
        ForeignKeyConstraint(
            ["category_id", "spreadsheet_id"],
            ["categories.id", "categories.spreadsheet_id"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_records_category_id_categories",
        ),
        ForeignKeyConstraint(
            ["source_id", "spreadsheet_id"],
            ["sources.id", "sources.spreadsheet_id"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_records_source_id_sources",
        ),
        ForeignKeyConstraint(
            ["check_id", "spreadsheet_id"],
            ["checks.id", "checks.spreadsheet_id"],
            deferrable=True,
            initially="DEFERRED",
            name="fk_records_check_id_checks",
        ),
        # Лист операций периода.
        Index(
            "ix_records_period_id_alive",
            "period_id",
            "id",
            postgresql_where="deleted_at IS NULL",
        ),
        # Агрегат баланса счёта.
        Index(
            "ix_records_source_id_alive",
            "source_id",
            postgresql_where="deleted_at IS NULL",
        ),
        # Дневные итоги по категориям для листа статистики.
        Index(
            "ix_records_category_id_alive",
            "category_id",
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_records_spreadsheet_id_added_at",
            "spreadsheet_id",
            "added_at",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    added_at: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str] = mapped_column(
        String(constants.NOTES_MAX_LENGTH),
        nullable=False,
        server_default=text("''"),
    )
    product_name: Mapped[str | None] = mapped_column(
        String(constants.PRODUCT_NAME_MAX_LENGTH),
        nullable=True,
        default=None,
    )
    product_type: Mapped[str | None] = mapped_column(
        String(constants.PRODUCT_TYPE_MAX_LENGTH),
        nullable=True,
        default=None,
    )
    check_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
