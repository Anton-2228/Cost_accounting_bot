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
from checks_service.exceptions import (
    ApiError,
    CheckAlreadySavedError,
    PendingCheckBusyError,
    PendingCheckNotFoundError,
)
from checks_service.formats.base import CheckPreview, ParsedCheck
from checks_service.main_api.checks import SavedCheck
from checks_service.main_api.pending_checks import PendingCheck
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
        notice: dict[str, str] | None = None,
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
                "notice": notice,
            }
        )
        check_id = self.next_id
        self.next_id += 1
        return SavedCheck(id=check_id, kind=kind.value, external_key=external_key)


@dataclass
class FakePendingChecksClient:
    """Фейк клиента отложенных чеков: держит строки в памяти.

    Сохранение чека в api убирает отложенный с тем же ключом — фейк этого не
    умеет, потому что не видит `FakeChecksClient`; тесты, которым это важно,
    смотрят на журнал `saved` у клиента чеков.
    """

    rows: list[PendingCheck] = field(default_factory=list)
    keys: dict[int, str] = field(default_factory=dict)
    added: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[int] = field(default_factory=list)
    #: Id, которые «захвачены» кем-то другим: ручной повтор получит отказ.
    busy: set[int] = field(default_factory=set)
    #: Что вернёт фоновый захват.
    due: list[PendingCheck] = field(default_factory=list)
    next_id: int = 1

    def put(self, spreadsheet_id: int, kind: CheckKind, qr_raw: str) -> PendingCheck:
        """Кладёт отложенный чек, как будто его отложили раньше."""
        pending = PendingCheck(
            id=self.next_id,
            spreadsheet_id=spreadsheet_id,
            kind=kind,
            qr_raw=qr_raw,
            expired_at=None,
        )
        self.next_id += 1
        self.rows.append(pending)
        return pending

    async def add(
        self,
        spreadsheet_id: int,
        *,
        kind: CheckKind,
        qr_raw: str,
        external_key: str,
        error: str,
    ) -> PendingCheck:
        """Откладывает чек; тот же ключ возвращает ту же строку."""
        self.added.append({"spreadsheet_id": spreadsheet_id, "kind": kind, "error": error})
        for pending in self.rows:
            if self.keys.get(pending.id) == external_key:
                return pending
        pending = self.put(spreadsheet_id, kind, qr_raw)
        self.keys[pending.id] = external_key
        return pending

    async def list_for(self, spreadsheet_id: int) -> list[PendingCheck]:
        """Отложенные чеки документа."""
        return [row for row in self.rows if row.spreadsheet_id == spreadsheet_id]

    async def delete(self, spreadsheet_id: int, pending_id: int) -> None:
        """Убирает строку или отвечает «нет такой»."""
        self._find(spreadsheet_id, pending_id)
        self.rows = [row for row in self.rows if row.id != pending_id]
        self.deleted.append(pending_id)

    async def claim(self, spreadsheet_id: int, pending_id: int) -> PendingCheck:
        """Захват для ручного повтора."""
        pending = self._find(spreadsheet_id, pending_id)
        if pending_id in self.busy:
            raise PendingCheckBusyError("Чек уже запрашивается")
        return pending

    async def claim_due(self) -> list[PendingCheck]:
        """Фоновый захват: отдаёт заготовленное один раз."""
        due, self.due = self.due, []
        return due

    async def fail(
        self,
        pending_id: int,
        *,
        error: str,
        manual: bool,
        preview: CheckPreview,
    ) -> None:
        """Запоминает отчёт о неудаче."""
        self.failures.append({"id": pending_id, "error": error, "manual": manual})

    def _find(self, spreadsheet_id: int, pending_id: int) -> PendingCheck:
        for row in self.rows:
            if row.id == pending_id and row.spreadsheet_id == spreadsheet_id:
                return row
        raise PendingCheckNotFoundError("Отложенного чека нет")


@dataclass
class FakeUsersClient:
    """Фейк клиента пользователей: язык или отказ api."""

    #: Код языка, который «вернёт api»; `None` — пользователя api не знает.
    language_code: str | None = None
    fail_with: ApiError | None = None
    calls: list[int] = field(default_factory=list)

    async def language(self, telegram_id: int) -> str | None:
        """Язык пользователя или отказ."""
        self.calls.append(telegram_id)
        if self.fail_with is not None:
            raise self.fail_with
        return self.language_code


@dataclass
class FakeApiGateway:
    """Фейк шлюза к основному api."""

    spreadsheets: FakeSpreadsheetsClient = field(default_factory=FakeSpreadsheetsClient)
    checks: FakeChecksClient = field(default_factory=FakeChecksClient)
    pending_checks: FakePendingChecksClient = field(default_factory=FakePendingChecksClient)
    users: FakeUsersClient = field(default_factory=FakeUsersClient)

    async def aclose(self) -> None:
        """Закрывать нечего."""
