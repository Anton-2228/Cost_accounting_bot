"""ORM-модель сообщения пользователю о результате фоновой работы."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.core import constants
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

    Текста в строке нет — только `code` и `params`: фразу на языке пользователя
    собирает бот по своему каталогу. `kind` — класс события (по `TABLE_READY` бот
    ещё и дорисовывает меню), `code` — какая именно фраза: один вид события
    бывает рассказан по-разному (`SYNC_FAILED` — это и «не удаётся обновить», и
    «доступ не выдан»).

    Код — строка, а не нативный enum: новый код появляется вместе с шаблоном в
    каталоге бота, и `ALTER TYPE` на каждый был бы миграцией ради фразы.

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
    code: Mapped[str] = mapped_column(
        String(constants.NOTIFICATION_CODE_MAX_LENGTH),
        nullable=False,
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
