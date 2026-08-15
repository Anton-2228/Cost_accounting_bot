"""ORM-модель сообщения пользователю о результате фоновой работы."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import NOTIFICATION_KIND
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import NotificationKind


class UserNotificationORM(PkMixin, TimestampMixin, Base):
    """Исходящее сообщение пользователю, ожидающее отправки ботом.

    После разделения на сервисы у фоновой работы не осталось способа ответить
    пользователю синхронно. Старый `/sync` читал лист и возвращал ошибку разбора
    прямо в ответ на команду; теперь лист читает `google_sheets_service` по
    задаче из очереди, и ошибка рождается тогда, когда HTTP-запроса пользователя
    уже нет. Такие сообщения складываются сюда, а бот их вычитывает и печатает.

    `text` уже на русском и готов к отправке как есть. Это второе после ошибок
    разбора листа отступление от правила «русский текст живёт в боте», и по той
    же причине: сообщение собрано из пользовательских данных (номер строки,
    название листа), кодом ошибки его не выразить.

    Доставка подтверждается отдельно (`delivered_at`), а не удалением строки:
    падение бота между чтением и отправкой не должно терять сообщение.
    """

    __tablename__ = "user_notifications"
    __table_args__ = (
        # Бот спрашивает только недоставленные, и их всегда единицы, тогда как
        # доставленных копится история. Частичный индекс держит выборку
        # маленькой независимо от объёма истории.
        Index(
            "ix_user_notifications_undelivered",
            "spreadsheet_id",
            "id",
            postgresql_where="delivered_at IS NULL",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[NotificationKind] = mapped_column(NOTIFICATION_KIND, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
