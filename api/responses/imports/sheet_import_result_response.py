"""Response-схема результата импорта листа."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SheetImportResultResponse(BaseModel):
    """Что сделал импорт или почему не сделал ничего.

    `error` — единственное место, где русский текст для пользователя едет из api
    как **данные**: он собран из содержимого листа и номеров строк, поэтому
    выразить его кодом ошибки нельзя. Заполненное поле означает, что в БД не
    записано ничего.
    """

    model_config = ConfigDict(from_attributes=True)

    error: str | None
    created: int
    updated: int
    deleted: int
