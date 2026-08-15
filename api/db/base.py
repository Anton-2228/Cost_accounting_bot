"""Декларативная база SQLAlchemy с единым соглашением об именах constraint'ов.

Стабильные имена индексов и ключей нужны, чтобы на них можно было ссылаться из
кода: `ON CONFLICT ON CONSTRAINT uq_sheet_sync_tasks_key` в очереди перерисовки
листов сломается, если имя ограничения начнёт генерироваться по-разному.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
