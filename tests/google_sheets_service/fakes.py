"""Фейки Google и api для тестов сервиса синхронизации.

Все фейки ведут **упорядоченный журнал вызовов**: у движка нет возвращаемого
значения, по которому видно, что он сделал, а порядок действий здесь и есть
предмет проверки. Перерисовать лист до его создания или прочитать справочник до
того, как в него вернулись идентификаторы, — ошибки, которые видны только в
последовательности.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google_sheets_service.exceptions import GoogleApiError
from google_sheets_service.google.sheets_client import SheetProperties
from google_sheets_service.main_api.dto import (
    Access,
    Category,
    CategoryDailyTotal,
    Check,
    ImportResult,
    Period,
    Record,
    SheetMapping,
    Source,
    SourceBalance,
    Spreadsheet,
    SyncTask,
    Transfer,
)
from tests.google_sheets_service.factories import SPREADSHEET_CREATED_AT


@dataclass
class FakeSheetsClient:
    """Фейк клиента Sheets: помнит листы и записывает всё, что с ними делали."""

    layout: list[SheetProperties] = field(default_factory=list)
    values: dict[str, list[list[Any]]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    batches: list[list[dict[str, Any]]] = field(default_factory=list)
    created_spreadsheet_id: str = "google-new"
    #: Ошибка, которую клиент бросит на следующем `batch_update`.
    fail_batch_with: Exception | None = None
    connections_reset: int = 0
    _next_sheet_id: int = 1000

    def reset_connections(self) -> None:
        """Считает сбросы пула соединений."""
        self.connections_reset += 1

    async def create_spreadsheet(
        self,
        title: str,
        *,
        locale: str,
        sheets: list[dict[str, Any]],
    ) -> tuple[str, list[SheetProperties]]:
        """Создаёт документ вместе с перечисленными листами.

        Повторяет поведение Google: заводит ровно то, что попросили. Если бы
        список был пуст, настоящий Google создал бы собственный «Лист1» — ради
        того, чтобы этого не случалось, листы и передаются явно.
        """
        self.calls.append(f"create_spreadsheet:{title}")
        created: list[SheetProperties] = []
        for sheet in sheets:
            self._next_sheet_id += 1
            properties = sheet["properties"]
            grid = properties.get("gridProperties", {})
            created.append(
                SheetProperties(
                    sheet_id=self._next_sheet_id,
                    title=str(properties["title"]),
                    row_count=int(grid.get("rowCount", 0)),
                    column_count=int(grid.get("columnCount", 0)),
                )
            )
        self.layout.extend(created)
        return self.created_spreadsheet_id, created

    async def get_layout(self, spreadsheet_id: str) -> list[SheetProperties]:
        """Возвращает заранее выложенные листы."""
        self.calls.append("get_layout")
        return list(self.layout)

    async def batch_update(
        self,
        spreadsheet_id: str,
        requests: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Применяет пачку запросов, отвечая на каждый `addSheet` новым листом."""
        if self.fail_batch_with is not None:
            error, self.fail_batch_with = self.fail_batch_with, None
            raise error

        self.batches.append(requests)
        self.calls.append(f"batch_update:{_batch_kinds(requests)}")

        replies: list[dict[str, Any]] = []
        for request in requests:
            if "addSheet" not in request:
                replies.append({})
                continue
            self._next_sheet_id += 1
            properties = dict(request["addSheet"]["properties"])
            properties["sheetId"] = self._next_sheet_id
            grid = properties.get("gridProperties", {})
            self.layout.append(
                SheetProperties(
                    sheet_id=self._next_sheet_id,
                    title=str(properties["title"]),
                    row_count=int(grid.get("rowCount", 0)),
                    column_count=int(grid.get("columnCount", 0)),
                )
            )
            replies.append({"addSheet": {"properties": properties}})
        return replies

    async def get_values(self, spreadsheet_id: str, range_a1: str) -> list[list[Any]]:
        """Возвращает заранее подложенные значения диапазона."""
        self.calls.append(f"get_values:{range_a1}")
        return self.values.get(range_a1, [])


@dataclass
class FakeDriveClient:
    """Фейк клиента Drive: метки документов и выданные доступы."""

    known_files: dict[str, str] = field(default_factory=dict)
    granted: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    #: Почты, на которые Google откажется выдавать доступ.
    reject_emails: set[str] = field(default_factory=set)

    async def find_by_app_property(self, key: str, value: str) -> str | None:
        """Ищет документ по метке."""
        self.calls.append(f"find:{value}")
        return self.known_files.get(value)

    async def set_app_property(self, file_id: str, key: str, value: str) -> None:
        """Ставит метку документу."""
        self.calls.append(f"mark:{file_id}={value}")
        self.known_files[value] = file_id

    async def grant_access(self, file_id: str, email: str, *, role: str) -> None:
        """Выдаёт доступ или отказывает, если почта в списке отвергаемых."""
        self.calls.append(f"grant:{email}")
        if email in self.reject_emails:
            raise GoogleApiError("Неверный адрес", status_code=400)
        self.granted.append(email)


@dataclass
class FakeTasksClient:
    """Фейк очереди задач."""

    queue: list[SyncTask] = field(default_factory=list)
    completed: list[int] = field(default_factory=list)
    failures: list[tuple[int, str, bool]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def claim(self, limit: int) -> list[SyncTask]:
        """Отдаёт всю очередь разом и очищает её."""
        self.calls.append("claim")
        claimed, self.queue = self.queue[:limit], self.queue[limit:]
        return claimed

    async def complete(self, task: SyncTask) -> None:
        """Отмечает задачу выполненной."""
        self.calls.append(f"complete:{task.id}")
        self.completed.append(task.id)

    async def fail(self, task: SyncTask, error: str, *, terminal: bool = False) -> None:
        """Отмечает задачу неудавшейся."""
        self.calls.append(f"fail:{task.id}:{terminal}")
        self.failures.append((task.id, error, terminal))


@dataclass
class FakeSpreadsheetsClient:
    """Фейк клиента документа и справочников."""

    spreadsheet: Spreadsheet = field(
        default_factory=lambda: Spreadsheet(
            id=1,
            google_spreadsheet_id="google-1",
            title="Проверка",
            reset_day=1,
            timezone="Europe/Moscow",
            created_at=SPREADSHEET_CREATED_AT,
        )
    )
    categories: list[Category] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    balances: list[SourceBalance] = field(default_factory=list)
    pending_accesses: list[Access] = field(default_factory=list)
    granted_ids: list[int] = field(default_factory=list)
    failed_ids: list[int] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def get(self, spreadsheet_id: int) -> Spreadsheet:
        """Документ."""
        self.calls.append("get_spreadsheet")
        return self.spreadsheet

    async def set_google_id(self, spreadsheet_id: int, google_spreadsheet_id: str) -> Spreadsheet:
        """Привязывает документ Google."""
        self.calls.append(f"set_google_id:{google_spreadsheet_id}")
        self.spreadsheet = Spreadsheet(
            id=self.spreadsheet.id,
            google_spreadsheet_id=google_spreadsheet_id,
            title=self.spreadsheet.title,
            reset_day=self.spreadsheet.reset_day,
            timezone=self.spreadsheet.timezone,
            created_at=self.spreadsheet.created_at,
        )
        return self.spreadsheet

    async def list_pending_accesses(self, spreadsheet_id: int) -> list[Access]:
        """Невыданные доступы."""
        self.calls.append("list_pending_accesses")
        return list(self.pending_accesses)

    async def mark_access_granted(self, spreadsheet_id: int, access_id: int) -> None:
        """Отмечает доступ выданным."""
        self.calls.append(f"access_granted:{access_id}")
        self.granted_ids.append(access_id)

    async def mark_access_failed(self, spreadsheet_id: int, access_id: int) -> None:
        """Отмечает доступ невыдаваемым."""
        self.calls.append(f"access_failed:{access_id}")
        self.failed_ids.append(access_id)

    async def list_categories(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Category]:
        """Категории."""
        self.calls.append(f"list_categories:active={only_active}:deleted={include_deleted}")
        if only_active:
            return [item for item in self.categories if item.status == "ACTIVE"]
        return list(self.categories)

    async def list_sources(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Source]:
        """Счета."""
        self.calls.append("list_sources")
        return list(self.sources)

    async def list_balances(self, spreadsheet_id: int) -> list[SourceBalance]:
        """Балансы."""
        self.calls.append("list_balances")
        return list(self.balances)


@dataclass
class FakeSheetMappingsClient:
    """Фейк соответствий «адресат → лист»."""

    mappings: list[SheetMapping] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    _next_id: int = 100

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[SheetMapping]:
        """Известные листы."""
        self.calls.append("list_mappings")
        return list(self.mappings)

    async def upsert(
        self,
        spreadsheet_id: int,
        *,
        target: str,
        google_sheet_id: int,
        title: str,
        period_id: int | None = None,
    ) -> SheetMapping:
        """Запоминает лист."""
        self.calls.append(f"upsert_mapping:{target}:{period_id}")
        self._next_id += 1
        mapping = SheetMapping(
            id=self._next_id,
            target=target,
            period_id=period_id,
            google_sheet_id=google_sheet_id,
            title=title,
        )
        self.mappings = [item for item in self.mappings if item.key != mapping.key]
        self.mappings.append(mapping)
        return mapping


@dataclass
class FakePeriodsClient:
    """Фейк периодов и статистики."""

    periods: list[Period] = field(default_factory=list)
    totals: list[CategoryDailyTotal] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def list_all(self, spreadsheet_id: int) -> list[Period]:
        """Периоды."""
        self.calls.append("list_periods")
        return list(self.periods)

    async def statistics(self, spreadsheet_id: int, period_id: int) -> list[CategoryDailyTotal]:
        """Дневные итоги."""
        self.calls.append(f"statistics:{period_id}")
        return list(self.totals)


@dataclass
class FakeOperationsClient:
    """Фейк операций и переводов."""

    records: list[Record] = field(default_factory=list)
    transfers: list[Transfer] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def list_records(self, spreadsheet_id: int, period_id: int) -> list[Record]:
        """Операции периода."""
        self.calls.append(f"list_records:{period_id}")
        return list(self.records)

    async def list_transfers(self, spreadsheet_id: int, period_id: int) -> list[Transfer]:
        """Переводы периода."""
        self.calls.append(f"list_transfers:{period_id}")
        return list(self.transfers)


@dataclass
class FakeChecksClient:
    """Фейк архива чеков."""

    checks: list[Check] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def list_by_period(self, spreadsheet_id: int, period_id: int) -> list[Check]:
        """Чеки периода."""
        self.calls.append(f"list_checks:{period_id}")
        return list(self.checks)


@dataclass
class FakeImportsClient:
    """Фейк импорта справочников."""

    result: ImportResult = field(
        default_factory=lambda: ImportResult(error=None, created=0, updated=0, deleted=0)
    )
    received: list[tuple[str, list[list[str]]]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def import_categories(
        self,
        spreadsheet_id: int,
        rows: list[list[str]],
    ) -> ImportResult:
        """Применяет лист категорий."""
        self.calls.append("import_categories")
        self.received.append(("CATEGORIES", [list(row) for row in rows]))
        return self.result

    async def import_bills(self, spreadsheet_id: int, rows: list[list[str]]) -> ImportResult:
        """Применяет лист счетов."""
        self.calls.append("import_bills")
        self.received.append(("BILLS", [list(row) for row in rows]))
        return self.result


@dataclass
class FakeApiGateway:
    """Фейк шлюза api: те же поля, что у настоящего."""

    tasks: FakeTasksClient = field(default_factory=FakeTasksClient)
    spreadsheets: FakeSpreadsheetsClient = field(default_factory=FakeSpreadsheetsClient)
    sheet_mappings: FakeSheetMappingsClient = field(default_factory=FakeSheetMappingsClient)
    periods: FakePeriodsClient = field(default_factory=FakePeriodsClient)
    operations: FakeOperationsClient = field(default_factory=FakeOperationsClient)
    checks: FakeChecksClient = field(default_factory=FakeChecksClient)
    imports: FakeImportsClient = field(default_factory=FakeImportsClient)

    @property
    def calls(self) -> list[str]:
        """Все вызовы api в порядке поступления."""
        merged: list[str] = []
        for client in (
            self.tasks,
            self.spreadsheets,
            self.sheet_mappings,
            self.periods,
            self.operations,
            self.checks,
            self.imports,
        ):
            merged.extend(client.calls)
        return merged

    async def aclose(self) -> None:
        """Ничего не закрывает: соединений нет."""


def _batch_kinds(requests: list[dict[str, Any]]) -> str:
    """Перечисляет виды запросов пачки — так журнал остаётся читаемым."""
    return ",".join(sorted({key for request in requests for key in request}))
