"""Перечисления сервиса.

Зеркало :mod:`api.enums`. Дублирование намеренно — ровно по той же причине, по
которой продублированы DTO в `google_sheets_service`: общего пакета схем нет, а
импорт `api` затащил бы сюда SQLAlchemy и подключение к Postgres. **Если
значение добавляется в `api/enums/check_kind.py`, его надо добавить и здесь**,
иначе api ответит 422 на вид, который сервис считает своим.
"""

from __future__ import annotations

from enum import StrEnum


class CheckKind(StrEnum):
    """Формат фискального чека."""

    RU_FNS = "RU_FNS"
    SRB_SUF = "SRB_SUF"
