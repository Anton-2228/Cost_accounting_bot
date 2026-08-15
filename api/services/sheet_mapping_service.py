"""Соответствие «адресат → лист Google-документа» (служебное, для gsheets)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.sheet_mapping import SheetMapping
from api.enums import SheetTarget
from api.exceptions.base import BusinessRuleError, NotFoundError
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_mapping_repository import SheetMappingRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services.base import BaseSpreadsheetService


class SheetMappingService(BaseSpreadsheetService):
    """Где именно в Google-документе лежит тот или иной лист.

    Хранит это api, а не `google_sheets_service`: тот не имеет своей базы и
    после перезапуска иначе не знал бы, создан ли уже лист периода.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        mappings: SheetMappingRepository,
        periods: PeriodRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._mappings = mappings
        self._periods = periods

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[SheetMapping]:
        """Все известные листы документа."""
        await self._get(spreadsheet_id)
        return await self._mappings.list_by_spreadsheet(spreadsheet_id)

    async def upsert(
        self,
        spreadsheet_id: int,
        *,
        target: SheetTarget,
        google_sheet_id: int,
        title: str,
        period_id: int | None = None,
    ) -> SheetMapping:
        """Запоминает созданный лист. Повторный вызов обновляет запись."""
        await self._get(spreadsheet_id)
        if target.requires_period != (period_id is not None):
            raise BusinessRuleError("Период указан не для того листа")
        if (
            period_id is not None
            and await self._periods.get_for_spreadsheet(period_id, spreadsheet_id) is None
        ):
            raise NotFoundError("period")

        mapping = await self._mappings.upsert(
            SheetMapping(
                spreadsheet_id=spreadsheet_id,
                target=target,
                period_id=period_id,
                google_sheet_id=google_sheet_id,
                title=title,
            )
        )
        await self._commit()
        return mapping
