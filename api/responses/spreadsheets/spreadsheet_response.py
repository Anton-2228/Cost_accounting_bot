"""Response-схема учётной таблицы."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from api.core.types import ResetDay


class SpreadsheetResponse(BaseModel):
    """Учётная таблица в ответе.

    Пустой `google_spreadsheet_id` — рабочее состояние «документ в Google ещё
    предстоит создать», по нему бот и понимает, что ссылку давать рано.

    `created_at` выдаётся наружу не ради показа: вместе с `id` он образует
    метку, которой `google_sheets_service` помечает созданный документ в Drive
    и по которой находит его при повторе. Одного `id` для этого мало — он
    уникален лишь в пределах одной жизни базы, и пересозданная база начинает
    нумерацию заново, попадая меткой в чужой документ от прежних запусков.

    `deleted_at` — метка отвязывания. Заполнено означает «документ отвязан», и
    в ответах, которые отдают только живые документы, оно всегда пусто. Поле
    отдаётся как факт из базы, а не как выведённый признак: единственный
    эндпоинт, показывающий отвязанные документы, — история пользователя, и
    отличать их там нужно по тому же значению, по которому их различает БД.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    google_spreadsheet_id: str | None
    title: str
    reset_day: ResetDay
    timezone: str
    created_at: datetime
    deleted_at: datetime | None = None
