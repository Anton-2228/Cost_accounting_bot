"""ORM-модель пользователя Telegram."""

from __future__ import annotations

from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.mixins import PkMixin, TimestampMixin


class UserORM(PkMixin, TimestampMixin, Base):
    """Пользователь бота, опознаваемый по telegram_id.

    `telegram_id` уникален. В старой схеме уникальности не было, и повторный
    `/start` создавал вторую пару «пользователь + документ»; какой из документов
    считался текущим, определял порядок строк в куче Postgres, то есть он менялся
    после любого `VACUUM`. Операции начинали уходить в другую таблицу без единой
    ошибки в логах.
    """

    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
