"""Фейки внешнего мира для тестов `checks_service`.

Фейки ведут журнал вызовов: у приёма чека почти нет возвращаемого значения, по
которому видно, что он сделал, а существенно именно то, **пошёл ли** он во
внешний сервис и **дошло ли** что-нибудь до api. «Расшифровка не удалась, а
чек всё равно сохранился» — ошибка, которую видно только так.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from checks_service.enums import CheckKind
from checks_service.exceptions import ApiError, CheckAlreadySavedError
from checks_service.formats.base import ParsedCheck
from checks_service.main_api.checks import SavedCheck
from checks_service.main_api.spreadsheets import Spreadsheet


@dataclass
class FakeFetcher:
    """Фейк внешнего сервиса расшифровки."""

    payload: dict[str, Any] = field(default_factory=dict)
    #: Ошибка, которую фетчер бросит вместо ответа.
    fail_with: Exception | None = None
    calls: list[ParsedCheck] = field(default_factory=list)

    async def fetch(self, parsed: ParsedCheck) -> dict[str, Any]:
        """Возвращает заготовленный ответ или падает."""
        self.calls.append(parsed)
        if self.fail_with is not None:
            raise self.fail_with
        return self.payload

    async def aclose(self) -> None:
        """Закрывать нечего."""


@dataclass
class FakeSpreadsheetsClient:
    """Фейк клиента документов."""

    spreadsheet: Spreadsheet | None = None
    calls: list[int] = field(default_factory=list)

    async def get_by_telegram(self, telegram_id: int) -> Spreadsheet | None:
        """Документ пользователя или `None`, если таблицы нет."""
        self.calls.append(telegram_id)
        return self.spreadsheet


@dataclass
class FakeChecksClient:
    """Фейк клиента чеков основного api."""

    saved: list[dict[str, Any]] = field(default_factory=list)
    #: Следующий вызов ответит «уже добавлен».
    already_saved: bool = False
    #: Следующий вызов ответит недоступностью api.
    fail_with: ApiError | None = None
    next_id: int = 1

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
        """Записывает чек в список или отвечает отказом."""
        if self.already_saved:
            raise CheckAlreadySavedError("Этот чек уже добавлен")
        if self.fail_with is not None:
            raise self.fail_with

        self.saved.append(
            {
                "spreadsheet_id": spreadsheet_id,
                "kind": kind,
                "qr_raw": qr_raw,
                "external_key": external_key,
                "raw_payload": raw_payload,
                "fetched_at": fetched_at,
            }
        )
        check_id = self.next_id
        self.next_id += 1
        return SavedCheck(id=check_id, kind=kind.value, external_key=external_key)


@dataclass
class FakeApiGateway:
    """Фейк шлюза к основному api."""

    spreadsheets: FakeSpreadsheetsClient = field(default_factory=FakeSpreadsheetsClient)
    checks: FakeChecksClient = field(default_factory=FakeChecksClient)

    async def aclose(self) -> None:
        """Закрывать нечего."""
