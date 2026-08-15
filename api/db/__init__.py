"""Слой доступа к БД: база, миксины, движок, сессия, границы транзакции.

Импорт модуля не имеет побочных эффектов кроме создания движка в
:mod:`api.db.engine`.
"""

from __future__ import annotations

from api.db.base import NAMING_CONVENTION, Base
from api.db.mixins import PkMixin, SoftDeleteMixin, TimestampMixin
from api.db.session import get_session
from api.db.transaction import commit

__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "PkMixin",
    "SoftDeleteMixin",
    "TimestampMixin",
    "commit",
    "get_session",
]
