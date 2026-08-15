"""Клиент чеков: сохранение расшифрованного чека в основном api."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from checks_service.enums import CheckKind
from checks_service.exceptions import ApiError, CheckAlreadySavedError
from checks_service.main_api.http import ApiHttpClient

#: Причина конфликта, которую api кладёт в `details.reason`. Общий 409 «нарушено
#: ограничение целостности» здесь не годится: для сканирующего «уже добавлен» —
#: не ошибка, а осмысленный ответ, и путать его с прочими конфликтами нельзя.
ALREADY_SAVED_REASON = "check_already_saved"


@dataclass(frozen=True)
class SavedCheck:
    """Сохранённый чек. Зеркало `api/responses/checks/check_response.py`."""

    id: int
    kind: str
    external_key: str

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> SavedCheck:
        """Собирает чек из ответа api."""
        return cls(
            id=int(body["id"]),
            kind=str(body["kind"]),
            external_key=str(body["external_key"]),
        )


class ChecksApiClient:
    """Запись чека в основное api."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def save(
        self,
        spreadsheet_id: int,
        *,
        kind: CheckKind,
        qr_raw: str,
        external_key: str,
        raw_payload: dict[str, Any],
        fetched_at: datetime,
    ) -> SavedCheck:
        """Сохраняет расшифрованный чек; повтор превращает в понятный отказ."""
        try:
            body = await self._http.post_data(
                f"/spreadsheets/{spreadsheet_id}/checks",
                body={
                    "kind": kind.value,
                    "qr_raw": qr_raw,
                    "external_key": external_key,
                    "raw_payload": raw_payload,
                    "fetched_at": fetched_at.isoformat(),
                },
                expected=httpx.codes.CREATED,
            )
        except ApiError as error:
            if _is_already_saved(error):
                raise CheckAlreadySavedError("Этот чек уже добавлен") from error
            raise
        return SavedCheck.from_json(body)


def _is_already_saved(error: ApiError) -> bool:
    """Отличает «этот чек уже есть» от прочих ответов api."""
    if error.api_status_code != httpx.codes.CONFLICT:
        return False
    body = error.body
    if not isinstance(body, dict):
        return False
    details = body.get("details")
    return isinstance(details, dict) and details.get("reason") == ALREADY_SAVED_REASON
