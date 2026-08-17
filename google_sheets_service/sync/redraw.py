"""Перерисовка листа: состояние базы → одно атомарное обновление."""

from __future__ import annotations

from google_sheets_service.exceptions import SyncError
from google_sheets_service.google.sheets_client import GoogleSheetsClient
from google_sheets_service.logging import get_logger
from google_sheets_service.main_api import ApiGateway
from google_sheets_service.sheets import layouts, requests
from google_sheets_service.sheets.layout import SheetLayout, SheetPayload
from google_sheets_service.sync import renderers
from google_sheets_service.sync.structure import DocumentState

logger = get_logger(__name__)


class SheetRedrawer:
    """Строит лист заново из текущего состояния базы.

    Задача очереди говорит только «этот лист устарел», без подробностей о том,
    что именно изменилось. Поэтому лист собирается целиком: повтор безопасен,
    порядок обработки не важен, а потерянная задача чинится следующей же
    правкой.
    """

    def __init__(self, *, api: ApiGateway, sheets: GoogleSheetsClient) -> None:
        self._api = api
        self._sheets = sheets

    async def redraw(self, state: DocumentState, target: str, period_id: int | None) -> None:
        """Перерисовывает один лист."""
        payload, layout, sheet_id = await self._build(state, target, period_id)
        batch = requests.redraw_requests(
            sheet_id,
            layout,
            payload,
            sheet_row_count=state.row_count(sheet_id),
        )
        if not batch:
            return
        await self._sheets.batch_update(state.google_id, batch)
        logger.info(
            "Перерисован лист %s (период %s) документа %s: строк %s",
            target,
            period_id,
            state.spreadsheet.id,
            payload.row_count,
        )

    async def _build(
        self,
        state: DocumentState,
        target: str,
        period_id: int | None,
    ) -> tuple[SheetPayload, SheetLayout, int]:
        """Готовит содержимое листа, его описание и номер в документе."""
        spreadsheet_id = state.spreadsheet.id
        mapping = state.mapping(target, period_id)

        if target == "CATEGORIES":
            categories = await self._api.spreadsheets.list_categories(spreadsheet_id)
            return renderers.render_categories(categories), layouts.CATEGORIES_LAYOUT, \
                mapping.google_sheet_id

        if target == "BILLS":
            sources = await self._api.spreadsheets.list_sources(spreadsheet_id)
            balances = await self._api.spreadsheets.list_balances(spreadsheet_id)
            return renderers.render_bills(sources, balances), layouts.BILLS_LAYOUT, \
                mapping.google_sheet_id

        if period_id is None:
            raise SyncError(f"Адресату {target} нужен период")

        if target == "OPERATIONS":
            records = await self._api.operations.list_records(spreadsheet_id, period_id)
            transfers = await self._api.operations.list_transfers(spreadsheet_id, period_id)
            # Справочники с удалёнными: операция удалённой категории остаётся в
            # реестре навсегда, и её названию неоткуда взяться иначе.
            categories = await self._api.spreadsheets.list_categories(
                spreadsheet_id, include_deleted=True
            )
            sources = await self._api.spreadsheets.list_sources(
                spreadsheet_id, include_deleted=True
            )
            payload = renderers.render_operations(records, transfers, categories, sources)
            return payload, layouts.OPERATIONS_LAYOUT, mapping.google_sheet_id

        if target == "CHECKS":
            checks = await self._api.checks.list_by_period(spreadsheet_id, period_id)
            return renderers.render_checks(checks), layouts.CHECKS_LAYOUT, \
                mapping.google_sheet_id

        if target == "STATISTICS":
            period = state.period(period_id)
            categories = await self._api.spreadsheets.list_categories(
                spreadsheet_id, only_active=True
            )
            totals = await self._api.periods.statistics(spreadsheet_id, period_id)
            payload = renderers.render_statistics(
                categories,
                totals,
                start_date=period.start_date,
                end_date=period.end_date,
                sheet_id=mapping.google_sheet_id,
            )
            layout = layouts.statistics_layout(period.start_date, period.end_date)
            return payload, layout, mapping.google_sheet_id

        raise SyncError(f"Неизвестный адресат перерисовки: {target}")
