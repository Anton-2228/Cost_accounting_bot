"""Request-схема импорта строк листа."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ImportRowsRequest(BaseModel):
    """Сырые строки листа от `google_sheets_service`.

    Именно сырые: api в Google не ходит, а разбор и все русские тексты ошибок
    живут в :mod:`api.validation`. Короткие строки допустимы — Google обрезает
    хвостовые пустые ячейки, и выравнивание делает сам сервис.
    """

    model_config = ConfigDict(extra="forbid")

    rows: list[list[str]]
