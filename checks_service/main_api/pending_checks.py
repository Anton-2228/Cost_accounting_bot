"""Клиент отложенных чеков: учёт в основном api того, что пока не удалось получить."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from checks_service.enums import CheckKind
from checks_service.exceptions import (
    ApiError,
    CheckAlreadySavedError,
    PendingCheckBusyError,
    PendingCheckNotFoundError,
)
from checks_service.formats.base import CheckPreview
from checks_service.main_api.checks import is_conflict
from checks_service.main_api.http import ApiHttpClient

#: Причины конфликтов, которые api кладёт в `details.reason`.
ALREADY_SAVED_REASON = "check_already_saved"
BUSY_REASON = "pending_check_busy"


@dataclass(frozen=True)
class PendingCheck:
    """Отложенный чек. Зеркало `api/responses/pending_checks/pending_check_response.py`."""

    id: int
    spreadsheet_id: int
    kind: CheckKind
    qr_raw: str
    expired_at: datetime | None

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> PendingCheck:
        """Собирает чек из ответа api."""
        expired_at = body.get("expired_at")
        return cls(
            id=int(body["id"]),
            spreadsheet_id=int(body["spreadsheet_id"]),
            kind=CheckKind(body["kind"]),
            qr_raw=str(body["qr_raw"]),
            expired_at=None if expired_at is None else datetime.fromisoformat(expired_at),
        )


def notice_body(preview: CheckPreview) -> dict[str, str] | None:
    """Сводка чека для уведомления или `None`, если назвать чек нечем.

    Оба поля обязательны: без суммы или дня уведомление не скажет, о каком
    чеке речь. Оба нынешних формата несут их в QR-строке всегда.
    """
    if preview.total is None or preview.purchased_at is None:
        return None
    return {"total": str(preview.total), "purchased_at": preview.purchased_at.isoformat()}


class PendingChecksApiClient:
    """Отложенные чеки в основном api: завести, перечислить, захватить, отчитаться."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def add(
        self,
        spreadsheet_id: int,
        *,
        kind: CheckKind,
        qr_raw: str,
        external_key: str,
        error: str,
    ) -> PendingCheck:
        """Откладывает чек; уже отложенный api вернёт как есть."""
        try:
            body = await self._http.post_data(
                f"/spreadsheets/{spreadsheet_id}/pending-checks",
                body={
                    "kind": kind.value,
                    "qr_raw": qr_raw,
                    "external_key": external_key,
                    "error": error,
                },
                expected=httpx.codes.CREATED,
            )
        except ApiError as error_:
            if is_conflict(error_, ALREADY_SAVED_REASON):
                raise CheckAlreadySavedError("Этот чек уже добавлен") from error_
            raise
        return PendingCheck.from_json(body)

    async def list_for(self, spreadsheet_id: int) -> list[PendingCheck]:
        """Отложенные чеки документа в порядке сканирования."""
        items = await self._http.get_items(f"/spreadsheets/{spreadsheet_id}/pending-checks")
        return [PendingCheck.from_json(item) for item in items]

    async def delete(self, spreadsheet_id: int, pending_id: int) -> None:
        """Убирает отложенный чек."""
        try:
            await self._http.delete(f"/spreadsheets/{spreadsheet_id}/pending-checks/{pending_id}")
        except ApiError as error:
            raise _not_found_or(error) from error

    async def claim(self, spreadsheet_id: int, pending_id: int) -> PendingCheck:
        """Захватывает чек для ручного повтора."""
        try:
            body = await self._http.post_data(
                f"/spreadsheets/{spreadsheet_id}/pending-checks/{pending_id}/claim"
            )
        except ApiError as error:
            if is_conflict(error, BUSY_REASON):
                raise PendingCheckBusyError("Чек уже запрашивается") from error
            raise _not_found_or(error) from error
        return PendingCheck.from_json(body)

    async def claim_due(self) -> list[PendingCheck]:
        """Забирает чеки, которым пора повторить запрос."""
        items = await self._http.post_items("/pending-checks/claim")
        return [PendingCheck.from_json(item) for item in items]

    async def fail(
        self,
        pending_id: int,
        *,
        error: str,
        manual: bool,
        preview: CheckPreview,
    ) -> None:
        """Отчитывается о неудачной попытке; api назначит следующую."""
        await self._http.post_no_content(
            f"/pending-checks/{pending_id}/fail",
            body={"error": error, "manual": manual, "notice": notice_body(preview)},
        )


def _not_found_or(error: ApiError) -> Exception:
    """404 api — «отложенного чека нет», прочее — как есть."""
    if error.api_status_code == httpx.codes.NOT_FOUND:
        return PendingCheckNotFoundError("Отложенного чека нет")
    return error
