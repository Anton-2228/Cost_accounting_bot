"""ORM-модель отложенного чека: отсканирован, но ещё не расшифрован."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import CHECK_KIND
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import CheckKind


class PendingCheckORM(PkMixin, TimestampMixin, Base):
    """Чек, который внешний сервис пока не отдал, — и попытки его получить.

    Живёт отдельно от `checks`, а не строкой со статусом в ней: чек в `checks`
    всегда полный, и разбор не обязан уметь работать с получеками. Здесь лежит
    только то, из чего чек можно запросить заново, — QR-строка и вид формата.

    Строка исчезает, когда чек сохранён (`CheckService.save` удаляет её в той
    же транзакции) или когда пользователь удалил её сам. Истёкшая строка
    (`expired_at`) не удаляется: фон её больше не трогает, но в Mini App она
    остаётся, и ручной повтор возвращает её в работу.

    Захват устроен как у `sheet_sync_tasks`: `claimed_at` со сроком аренды,
    чтобы умерший между захватом и отчётом воркер не запер чек навсегда.
    """

    __tablename__ = "pending_checks"
    __table_args__ = (
        # Один и тот же чек откладывается один раз: повторный скан возвращает
        # уже существующую строку, а не заводит вторую очередь попыток.
        UniqueConstraint(
            "spreadsheet_id",
            "kind",
            "external_key",
            name="uq_pending_checks_spreadsheet_id_kind_external_key",
        ),
        # Выборка фона: неистёкшие строки, у которых подошёл срок.
        Index(
            "ix_pending_checks_due",
            "next_attempt_at",
            postgresql_where="expired_at IS NULL",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[CheckKind] = mapped_column(CHECK_KIND, nullable=False)
    #: Строка ровно так, как её отдал сканер.
    qr_raw: Mapped[str] = mapped_column(Text, nullable=False)
    #: Ключ дедупликации в терминах формата — тот же, что у `checks`.
    external_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: Сколько раз уже спрашивали внешний сервис, включая сам скан.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: Начало окна фоновых попыток: скан или последний ручной повтор.
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    #: Окно истекло, фон сдался. Пусто — чек в работе.
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    #: Машинный код последнего отказа (`receipt_not_ready`, …) — для диагностики.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
