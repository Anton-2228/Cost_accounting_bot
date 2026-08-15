"""Response-схема задачи очереди листов."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.enums import SheetTarget, SyncTaskKind


class SheetSyncTaskResponse(BaseModel):
    """Задача в ответе.

    `spreadsheet_id` здесь нужен, в отличие от остальных схем: `claim` отдаёт
    задачи сразу по всем документам, и без него воркер не знал бы, какой именно
    документ перерисовывать.

    `requested_at` возвращается обязательно: именно его воркер присылает назад в
    `complete`, и по нему видно, не изменился ли лист, пока его рисовали.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    spreadsheet_id: int
    kind: SyncTaskKind
    target: SheetTarget
    period_id: int | None
    requested_at: datetime
    attempts: int
    last_error: str | None
