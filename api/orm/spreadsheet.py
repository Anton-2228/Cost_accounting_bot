"""ORM-модель учётной таблицы (Google-документа)."""

from __future__ import annotations

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from api.core import constants
from api.db.base import Base
from api.db.mixins import PkMixin, SoftDeleteMixin, TimestampMixin


class SpreadsheetORM(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Учётная таблица пользователя.

    `user_id` уникален **среди живых документов** — один пользователь ведёт ровно
    одну таблицу одновременно, но за жизнь их может быть сколько угодно.

    `google_spreadsheet_id` **допускает NULL**: api не ходит в Google API. Строка
    создаётся сразу, документ создаёт `google_sheets_service` по задаче
    `STRUCTURE` и возвращает идентификатор через api. Здесь NULL-ы должны
    считаться различными (несколько таблиц могут одновременно ждать создания),
    поэтому обычный `UNIQUE`, без `NULLS NOT DISTINCT`.

    `reset_day` ограничен 1..28: только при этом условии сдвиг «то же число
    следующего месяца» всегда даёт существующую дату.

    `timezone` — часовой пояс владельца в формате IANA. Именно в нём считаются
    границы суток и день сброса. В старой схеме дата операции проставлялась
    сервером как `TIMEZONE('utc-3', now())` при контейнере в UTC, из-за чего
    вечерние операции уезжали в соседний день, а на границе месяца — в чужой
    период.

    Удаление **мягкое**: `/table_unlink` отвязывает документ от бота, а записи
    учёта остаются. Физическое удаление шло каскадом от `users` и стирало заодно
    всю историю — включая учёт денег, потраченных на модель, которых уже не
    вернуть. Пользователь при этом не удаляется вовсе: он тот же человек, и
    после отвязывания заводит следующий документ обычным `/start`.
    """

    __tablename__ = "spreadsheets"
    __table_args__ = (
        CheckConstraint(
            f"reset_day BETWEEN {constants.MIN_RESET_DAY} AND {constants.MAX_RESET_DAY}",
            name="reset_day_range",
        ),
        # Уникальность частичная, поэтому индекс, а не констрейнт: обычный
        # `UNIQUE` распространялся бы и на отвязанные документы, и первый же
        # `/start` после `/table_unlink` упирался бы в мёртвую строку.
        Index(
            "uq_spreadsheets_user_id",
            "user_id",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    google_spreadsheet_id: Mapped[str | None] = mapped_column(
        String(constants.GOOGLE_SPREADSHEET_ID_MAX_LENGTH),
        nullable=True,
        unique=True,
    )
    title: Mapped[str] = mapped_column(
        String(constants.SPREADSHEET_TITLE_MAX_LENGTH),
        nullable=False,
    )
    reset_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(constants.TIMEZONE_MAX_LENGTH),
        nullable=False,
        server_default=constants.DEFAULT_TIMEZONE,
    )
