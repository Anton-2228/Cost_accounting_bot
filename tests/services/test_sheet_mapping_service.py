"""Тесты соответствия «адресат → лист документа»."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import SheetTarget
from api.exceptions.base import BusinessRuleError, NotFoundError
from api.services.sheet_mapping_service import SheetMappingService
from tests import factories


async def test_upsert_remembers_sheet_and_updates_on_repeat(
    session: AsyncSession,
    sheet_mapping_service: SheetMappingService,
) -> None:
    """Повторная запись обновляет, а не дублирует.

    Соответствие хранит api: у `google_sheets_service` нет своей базы, и после
    перезапуска он иначе не знал бы, создан ли уже лист.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await sheet_mapping_service.upsert(
        spreadsheet.id,
        target=SheetTarget.CATEGORIES,
        google_sheet_id=11,
        title="Categories",
    )
    await sheet_mapping_service.upsert(
        spreadsheet.id,
        target=SheetTarget.CATEGORIES,
        google_sheet_id=22,
        title="Categories",
    )

    mappings = await sheet_mapping_service.list_by_spreadsheet(spreadsheet.id)
    assert [(item.target, item.google_sheet_id) for item in mappings] == [
        (SheetTarget.CATEGORIES, 22)
    ]


async def test_period_sheet_requires_period(
    session: AsyncSession,
    sheet_mapping_service: SheetMappingService,
) -> None:
    """У листа периода период обязателен, у остальных — недопустим.

    Это же различие закреплено двусторонним CHECK в БД: односторонняя проверка
    пропустила бы задачу `CATEGORIES` с периодом, и та висела бы вечно.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and period.id is not None

    with pytest.raises(BusinessRuleError):
        await sheet_mapping_service.upsert(
            spreadsheet.id,
            target=SheetTarget.OPERATIONS,
            google_sheet_id=1,
            title="2026-07-15",
        )

    with pytest.raises(BusinessRuleError):
        await sheet_mapping_service.upsert(
            spreadsheet.id,
            target=SheetTarget.CATEGORIES,
            google_sheet_id=1,
            title="Categories",
            period_id=period.id,
        )

    mapping = await sheet_mapping_service.upsert(
        spreadsheet.id,
        target=SheetTarget.OPERATIONS,
        google_sheet_id=1,
        title="2026-07-15",
        period_id=period.id,
    )
    assert mapping.period_id == period.id


async def test_period_of_another_document_is_not_found(
    session: AsyncSession,
    sheet_mapping_service: SheetMappingService,
) -> None:
    """Период чужого документа — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    stranger = await factories.create_spreadsheet(session, ready=True)
    alien_period = await factories.create_period(session, stranger)
    await session.commit()
    assert spreadsheet.id is not None and alien_period.id is not None

    with pytest.raises(NotFoundError):
        await sheet_mapping_service.upsert(
            spreadsheet.id,
            target=SheetTarget.STATISTICS,
            google_sheet_id=5,
            title="Stat. 2026-07-15",
            period_id=alien_period.id,
        )
