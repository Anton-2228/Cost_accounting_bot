"""Результат вчитывания правок с листа."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from api.domain.user_message import UserMessage


class SheetImportResult(BaseModel):
    """Что сделал импорт или почему он ничего не сделал.

    `error` — отказ кодом и данными для подстановки (см. :mod:`api.validation`):
    фразу на языке пользователя собирает бот. Он приходит вместе с гарантией:
    если поле заполнено, в БД **не записано ничего**. Лист правится целиком, и
    применить его половину значит оставить справочник в состоянии, которого
    пользователь не задумывал.
    """

    model_config = ConfigDict(from_attributes=True)

    error: UserMessage | None = None
    created: int = 0
    updated: int = 0
    deleted: int = 0
