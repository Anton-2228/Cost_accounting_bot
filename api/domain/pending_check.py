"""Доменная модель отложенного чека."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import CheckKind


class PendingCheck(BaseModel):
    """Отсканированный чек, который внешний сервис пока не отдал.

    Хранит только то, из чего чек можно запросить заново. Сумма и дата покупки
    для списка в Mini App достаются из `qr_raw` в `checks_service`, который
    знает форматы, — api их не интерпретирует, как и у сохранённых чеков.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    kind: CheckKind
    qr_raw: str
    external_key: str
    attempts: int = 1
    window_started_at: datetime | None = None
    next_attempt_at: datetime
    claimed_at: datetime | None = None
    expired_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
