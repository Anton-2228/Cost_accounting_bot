"""ORM-модель задачи на перерисовку листа (очередь исходящих изменений)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import SHEET_TARGET, SYNC_TASK_KIND
from api.db.mixins import PkMixin
from api.enums import SheetTarget, SyncTaskKind


class SheetSyncTaskORM(PkMixin, Base):
    """Отметка «лист устарел и подлежит перерисовке».

    Ключевой инвариант: **строка описывает не изменение, а устаревание.** Она не
    несёт данных о том, что именно произошло, — только адрес листа. Перерисовка
    всегда строится из текущего состояния БД целиком, поэтому повтор безопасен,
    порядок обработки не важен, а единственный возможный сбой — потеря задачи,
    которая чинится следующим же изменением или ручной синхронизацией.

    Задача пишется в **той же транзакции**, что и само изменение данных. Отсюда
    главное свойство новой архитектуры: api не ходит в Google, операция
    завершается за десятки миллисекунд и не может ответить пользователю ошибкой
    после того, как деньги уже списаны. Старая версия коммитила запись, а затем
    синхронно писала в Google; таймаут на этом вызове давал пользователю
    «Сервис данных недоступен», тот повторял команду — и получал двойное
    списание.

    Уникальный ключ схлопывает поток правок: десять быстрых операций подряд
    оставляют одну строку, и лист перерисовывается один раз, а не десять.

    ``UNIQUE NULLS NOT DISTINCT`` обязателен и требует PostgreSQL 15+. У листов
    `CATEGORIES`, `BILLS` и `STRUCTURE` периода нет, то есть `period_id IS NULL`;
    по умолчанию Postgres считает NULL-ы различными, и схлопывание для них
    просто не сработало бы — задачи копились бы без предела.
    """

    __tablename__ = "sheet_sync_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["period_id", "spreadsheet_id"],
            ["periods.id", "periods.spreadsheet_id"],
            ondelete="CASCADE",
            name="fk_sheet_sync_tasks_period_id_periods",
        ),
        UniqueConstraint(
            "spreadsheet_id",
            "kind",
            "target",
            "period_id",
            name="uq_sheet_sync_tasks_key",
            postgresql_nulls_not_distinct=True,
        ),
        # Условие двустороннее намеренно. Односторонняя формулировка
        # «OPERATIONS требует период» пропустила бы задачу CATEGORIES с
        # проставленным периодом: она не совпала бы по ключу с нормальной
        # задачей CATEGORIES, не схлопнулась бы и осталась висеть навсегда.
        CheckConstraint(
            "(target IN ('OPERATIONS', 'STATISTICS', 'CHECKS')) = (period_id IS NOT NULL)",
            name="period_matches_target",
        ),
        # Читать обратно можно только справочники: лист операций и статистика
        # целиком производны от БД. Вместе с ограничением выше это делает
        # «импорт листа операций» и «импорт с периодом» невыразимыми.
        CheckConstraint(
            "kind <> 'IMPORT' OR target IN ('CATEGORIES', 'BILLS')",
            name="import_target",
        ),
        # Выборка воркером: задачи, у которых подошёл срок и истёк захват.
        # Индекс намеренно полный, а не партиальный по `claimed_at IS NULL`:
        # выборка отбирает ещё и просроченные захваты, и такое условие
        # партиальный индекс не покрывает.
        Index(
            "ix_sheet_sync_tasks_claimable",
            "claimed_at",
            "next_attempt_at",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: Направление работы. Входит в уникальный ключ: перерисовка листа и чтение
    #: правок с него — разные задачи, схлопывать их в одну строку нельзя.
    kind: Mapped[SyncTaskKind] = mapped_column(
        SYNC_TASK_KIND,
        nullable=False,
        server_default=SyncTaskKind.REDRAW.value,
    )
    target: Mapped[SheetTarget] = mapped_column(SHEET_TARGET, nullable=False)
    period_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    #: Момент последнего запроса на перерисовку. Служит меткой версии: воркер
    #: удаляет задачу только если значение не изменилось, пока он работал.
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
