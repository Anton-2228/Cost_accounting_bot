"""Фикстуры движка: собранный на фейках граф объектов."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast

import pytest

from google_sheets_service.google.sheets_client import SheetProperties
from google_sheets_service.main_api import ApiGateway
from google_sheets_service.sync.engine import SyncEngine
from google_sheets_service.sync.importer import SheetImporter
from google_sheets_service.sync.pacer import Pacer
from google_sheets_service.sync.redraw import SheetRedrawer
from google_sheets_service.sync.structure import StructureSynchronizer
from tests.google_sheets_service.factories import make_mapping, make_period, make_spreadsheet
from tests.google_sheets_service.fakes import FakeApiGateway, FakeDriveClient, FakeSheetsClient


@dataclass
class Harness:
    """Собранный движок вместе с фейками, на которых он стоит."""

    engine: SyncEngine
    api: FakeApiGateway
    sheets: FakeSheetsClient
    drive: FakeDriveClient

    @property
    def calls(self) -> list[str]:
        """Обращения к Google в порядке поступления."""
        return self.sheets.calls + self.drive.calls


@pytest.fixture
def harness() -> Harness:
    """Движок на фейках, без пауз между задачами.

    Пауза выключена намеренно: в бою она бережёт квоту Google, а в тесте только
    удлиняла бы прогон.
    """
    api = FakeApiGateway()
    sheets = FakeSheetsClient()
    drive = FakeDriveClient()

    # Фейки повторяют форму настоящих клиентов, но не наследуют их: связывать
    # тесты с сигнатурами внутренних методов значило бы ломать их на каждом
    # переименовании.
    gateway = cast(ApiGateway, api)
    sheets_client = cast(Any, sheets)
    redrawer = SheetRedrawer(api=gateway, sheets=sheets_client)
    engine = SyncEngine(
        api=gateway,
        sheets=sheets_client,
        structure=StructureSynchronizer(
            api=gateway, sheets=sheets_client, drive=cast(Any, drive)
        ),
        redrawer=redrawer,
        importer=SheetImporter(api=gateway, sheets=sheets_client, redrawer=redrawer),
        pacer=Pacer(interval_seconds=0, stop=asyncio.Event()),
        claim_limit=20,
    )
    return Harness(engine=engine, api=api, sheets=sheets, drive=drive)


@pytest.fixture
def ready_harness(harness: Harness) -> Harness:
    """Движок над документом, у которого уже есть Google-таблица и все листы."""
    harness.api.spreadsheets.spreadsheet = make_spreadsheet()
    harness.api.periods.periods = [make_period()]
    harness.api.sheet_mappings.mappings = [
        make_mapping(mapping_id=1, target="CATEGORIES", google_sheet_id=11, title="Categories"),
        make_mapping(mapping_id=2, target="BILLS", google_sheet_id=12, title="Bills"),
        make_mapping(
            mapping_id=3,
            target="OPERATIONS",
            period_id=7,
            google_sheet_id=13,
            title="2026-08-01",
        ),
        make_mapping(
            mapping_id=4,
            target="STATISTICS",
            period_id=7,
            google_sheet_id=14,
            title="Stat. 2026-08-01",
        ),
    ]
    harness.sheets.layout = [
        SheetProperties(sheet_id=11, title="Categories", row_count=200, column_count=7),
        SheetProperties(sheet_id=12, title="Bills", row_count=200, column_count=6),
        SheetProperties(sheet_id=13, title="2026-08-01", row_count=200, column_count=9),
        SheetProperties(sheet_id=14, title="Stat. 2026-08-01", row_count=200, column_count=33),
    ]
    return harness
