"""Тесты очереди чеков."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.check_queue_item import CheckQueueItem
from api.repositories.check_queue_repository import CheckQueueRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_delete_requires_matching_spreadsheet(session: AsyncSession) -> None:
    """Чужой чек удалить нельзя.

    Прежний код удалял чек по одному лишь id, поэтому запрос с чужим
    идентификатором вычищал чужую очередь.
    """
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    await session.commit()

    assert other.id is not None
    assert mine.id is not None
    repository = CheckQueueRepository(session)
    item = await repository.add(CheckQueueItem(spreadsheet_id=other.id, check_text="t=2026..."))
    await session.commit()

    assert item.id is not None
    assert await repository.delete_for_spreadsheet(item.id, mine.id) is False
    assert await repository.count_by_spreadsheet(other.id) == 1

    assert await repository.delete_for_spreadsheet(item.id, other.id) is True
    await session.commit()
    assert await repository.count_by_spreadsheet(other.id) == 0


async def test_queue_is_ordered_by_arrival(session: AsyncSession) -> None:
    """Чеки разбираются в порядке поступления."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    assert spreadsheet.id is not None
    repository = CheckQueueRepository(session)
    for text in ("первый", "второй", "третий"):
        await repository.add(CheckQueueItem(spreadsheet_id=spreadsheet.id, check_text=text))
    await session.commit()

    items = await repository.list_by_spreadsheet(spreadsheet.id)
    assert [item.check_text for item in items] == ["первый", "второй", "третий"]
