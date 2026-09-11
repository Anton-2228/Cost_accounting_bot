"""Response-схема результата импорта листа."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from api.domain.sheet_import_result import SheetImportResult


class SheetImportResultResponse(BaseModel):
    """Что сделал импорт или почему не сделал ничего.

    `error` — код отказа (`import_error.unknown_id`, …), `error_params` — данные
    для подстановки: номер строки, название колонки. Фразу на языке
    пользователя по ним собирает бот, когда покажет уведомление; тому, кто
    вызвал импорт (`google_sheets_service`), достаточно знать, что отказано и
    почему. Заполненное поле означает, что в БД не записано ничего.
    """

    error: str | None
    error_params: dict[str, Any]
    created: int
    updated: int
    deleted: int

    @classmethod
    def from_domain(cls, result: SheetImportResult) -> SheetImportResultResponse:
        """Раскладывает отказ на код и параметры."""
        return cls(
            error=None if result.error is None else result.error.code,
            error_params={} if result.error is None else dict(result.error.params),
            created=result.created,
            updated=result.updated,
            deleted=result.deleted,
        )
