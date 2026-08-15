"""Тесты кэша «название товара → тип»."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.cashed_record import CashedRecord
from api.repositories.cashed_record_repository import CashedRecordRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_same_product_name_can_be_cached_by_different_spreadsheets(
    session: AsyncSession,
) -> None:
    """Кэш одного пользователя не мешает кэшу другого.

    В старой схеме `product_name` был уникален глобально: первый же
    пользователь, закэшировавший «молоко», навсегда ломал кэширование этого
    слова всем остальным — вставка падала, ошибка глушилась, и каждый чек
    требовал ручной классификации без единого объяснения.
    """
    first = await factories.create_spreadsheet(session)
    second = await factories.create_spreadsheet(session)
    await session.commit()

    assert first.id is not None
    assert second.id is not None
    repository = CashedRecordRepository(session)

    await repository.upsert(
        CashedRecord(spreadsheet_id=first.id, product_name="молоко", product_type="молочное")
    )
    await repository.upsert(
        CashedRecord(spreadsheet_id=second.id, product_name="молоко", product_type="напитки")
    )
    await session.commit()

    mine = await repository.get(first.id, "молоко")
    theirs = await repository.get(second.id, "молоко")
    assert mine is not None and mine.product_type == "молочное"
    assert theirs is not None and theirs.product_type == "напитки"


async def test_upsert_overwrites_previous_type(session: AsyncSession) -> None:
    """Повторное обучение перезаписывает тип, а не создаёт вторую запись."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    assert spreadsheet.id is not None
    repository = CashedRecordRepository(session)

    await repository.upsert(
        CashedRecord(spreadsheet_id=spreadsheet.id, product_name="сыр", product_type="молочное")
    )
    await repository.upsert(
        CashedRecord(spreadsheet_id=spreadsheet.id, product_name="сыр", product_type="деликатесы")
    )
    await session.commit()

    stored = await repository.list_by_spreadsheet(spreadsheet.id)
    assert len(stored) == 1
    assert stored[0].product_type == "деликатесы"


async def test_delete_by_product_types_forgets_whole_group(session: AsyncSession) -> None:
    """Когда тип перестаёт принадлежать категории, кэш по нему очищается."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    assert spreadsheet.id is not None
    repository = CashedRecordRepository(session)
    for name in ("молоко", "сыр"):
        await repository.upsert(
            CashedRecord(
                spreadsheet_id=spreadsheet.id, product_name=name, product_type="молочное"
            )
        )
    await repository.upsert(
        CashedRecord(spreadsheet_id=spreadsheet.id, product_name="хлеб", product_type="выпечка")
    )
    await session.commit()

    assert await repository.delete_by_product_types(spreadsheet.id, ["молочное"]) == 2
    await session.commit()

    remaining = await repository.list_by_spreadsheet(spreadsheet.id)
    assert [item.product_name for item in remaining] == ["хлеб"]


async def test_delete_by_empty_type_list_is_a_noop(session: AsyncSession) -> None:
    """Пустой список типов не приводит к запросу и ничего не удаляет."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    assert spreadsheet.id is not None
    repository = CashedRecordRepository(session)
    await repository.upsert(
        CashedRecord(spreadsheet_id=spreadsheet.id, product_name="хлеб", product_type="выпечка")
    )
    await session.commit()

    assert await repository.delete_by_product_types(spreadsheet.id, []) == 0
    assert len(await repository.list_by_spreadsheet(spreadsheet.id)) == 1
