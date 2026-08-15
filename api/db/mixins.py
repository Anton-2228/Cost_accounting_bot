"""Переиспользуемые миксины ORM-моделей: ключ, временные метки, мягкое удаление."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Identity, func
from sqlalchemy.orm import Mapped, mapped_column


class PkMixin:
    """Первичный ключ `BigInteger Identity` (автоинкремент на стороне БД)."""

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        primary_key=True,
    )


class TimestampMixin:
    """Временные метки создания и обновления (timezone-aware)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    """Мягкое удаление: `deleted_at IS NULL` означает «запись жива».

    Операции и переводы не удаляются физически — иначе разобраться в спорном
    балансе после ошибочного `/del` нечем. Категории и источники тоже: на них
    ссылаются исторические записи, и жёсткое удаление либо порвало бы ссылки,
    либо потребовало каскада, стирающего часть реестра.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
