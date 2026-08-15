"""Результат вчитывания правок с листа."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SheetImportResult(BaseModel):
    """Что сделал импорт или почему он ничего не сделал.

    `error` — готовый русский текст для пользователя (см. :mod:`api.validation`).
    Он приходит вместе с гарантией: если поле заполнено, в БД **не записано
    ничего**. Лист правится целиком, и применить его половину значит оставить
    справочник в состоянии, которого пользователь не задумывал.
    """

    model_config = ConfigDict(from_attributes=True)

    error: str | None = None
    created: int = 0
    updated: int = 0
    deleted: int = 0
