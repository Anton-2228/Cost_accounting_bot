"""Доменная модель задачи на перерисовку листа."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import SheetTarget, SyncTaskKind


class SheetSyncTask(BaseModel):
    """Отметка «лист устарел».

    `requested_at` играет роль версии: воркер удаляет задачу, только если
    значение не изменилось, пока он перерисовывал лист. Изменилось — значит за
    это время пришла новая правка, и лист надо перерисовать ещё раз.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    kind: SyncTaskKind = SyncTaskKind.REDRAW
    target: SheetTarget
    period_id: int | None = None
    requested_at: datetime | None = None
    claimed_at: datetime | None = None
    attempts: int = 0
    next_attempt_at: datetime | None = None
    last_error: str | None = None
