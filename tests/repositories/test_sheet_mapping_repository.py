"""Тесты соответствий «адресат перерисовки → лист документа»."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.sheet_mapping import SheetMapping
from api.enums import SheetTarget
from api.repositories.sheet_mapping_repository import SheetMappingRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_upsert_updates_existing_mapping(session: AsyncSession) -> None:
    """Повторная запись обновляет строку, а не добавляет вторую."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    assert spreadsheet.id is not None
    repository = SheetMappingRepository(session)

    await repository.upsert(
        SheetMapping(
            spreadsheet_id=spreadsheet.id,
            target=SheetTarget.CATEGORIES,
            google_sheet_id=0,
            title="Categories",
        )
    )
    await repository.upsert(
        SheetMapping(
            spreadsheet_id=spreadsheet.id,
            target=SheetTarget.CATEGORIES,
            google_sheet_id=5,
            title="Categories",
        )
    )
    await session.commit()

    stored = await repository.list_by_spreadsheet(spreadsheet.id)
    assert len(stored) == 1
    assert stored[0].google_sheet_id == 5


async def test_period_sheets_are_tracked_separately(session: AsyncSession) -> None:
    """Листы разных периодов не схлопываются друг с другом.

    Это и есть ответ на вопрос «созданы ли листы этого периода»: ролловер
    получает его запросом к БД, а не походом в Google.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    july = await factories.create_period(session, spreadsheet)
    await session.commit()

    assert spreadsheet.id is not None
    repository = SheetMappingRepository(session)

    assert await repository.get(spreadsheet.id, SheetTarget.OPERATIONS, july.id) is None

    await repository.upsert(
        SheetMapping(
            spreadsheet_id=spreadsheet.id,
            target=SheetTarget.OPERATIONS,
            period_id=july.id,
            google_sheet_id=11,
            title="2026-07-15",
        )
    )
    await session.commit()

    found = await repository.get(spreadsheet.id, SheetTarget.OPERATIONS, july.id)
    assert found is not None
    assert found.title == "2026-07-15"
