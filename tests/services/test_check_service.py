"""Тесты чеков: очередь, кэш типов и запись разобранного чека."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.domain.check_item import CheckItem, ProductTypeAssignment
from api.enums import CategoryKind, EntityStatus, SheetTarget
from api.exceptions.base import NotFoundError
from api.orm.record import RecordORM
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.services.check_service import CheckService
from tests import factories


async def test_queue_accepts_check_before_google_table_exists(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Очередь наполняется независимо от готовности таблицы.

    Внешнему источнику чеков незачем знать, дорисован ли Google-документ: чек
    полежит и дождётся разбора.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    item = await check_service.enqueue(spreadsheet.id, "{\"fn\": \"123\"}")
    assert item.id is not None
    assert item.check_text == "{\"fn\": \"123\"}"


async def test_commit_writes_whole_check_in_one_transaction(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Позиции, кэш, снятие с очереди и задачи — всё сразу.

    Прерывание на середине оставило бы половину чека в реестре, а половину
    потеряло, поэтому чек и приезжает одним запросом.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    food = await factories.create_category(session, spreadsheet, title="Еда")
    fun = await factories.create_category(session, spreadsheet, title="Развлечения")
    source = await factories.create_source(session, spreadsheet, start_balance=Decimal("1000.00"))
    await session.commit()
    assert spreadsheet.id is not None
    assert food.id is not None and fun.id is not None and source.id is not None

    queued = await check_service.enqueue(spreadsheet.id, "сырой чек")
    assert queued.id is not None

    records = await check_service.commit_check(
        spreadsheet.id,
        source_id=source.id,
        items=[
            CheckItem(
                product_name="молоко",
                product_type="продукты",
                category_id=food.id,
                amount=Decimal("89.90"),
            ),
            CheckItem(
                product_name="билет в кино",
                product_type="досуг",
                category_id=fun.id,
                amount=Decimal("450.00"),
            ),
        ],
        check_id=queued.id,
        check_json="сырой чек",
    )

    assert [record.amount for record in records] == [Decimal("-89.90"), Decimal("-450.00")]
    assert await check_service.list_queue(spreadsheet.id) == []

    cache = CashedRecordRepository(session)
    learned = await cache.get(spreadsheet.id, "молоко")
    assert learned is not None
    assert learned.product_type == "продукты"

    targets = {
        task.target
        for task in await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    }
    assert targets == {SheetTarget.OPERATIONS, SheetTarget.STATISTICS, SheetTarget.BILLS}


async def test_new_product_types_are_attached_and_redraw_categories(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Новый тип товара закрепляется за категорией и устаревает лист `Categories`."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    await check_service.commit_check(
        spreadsheet.id,
        source_id=source.id,
        items=[
            CheckItem(
                product_name="хлеб",
                product_type="продукты",
                category_id=category.id,
                amount=Decimal("40.00"),
            )
        ],
        new_product_types=[
            ProductTypeAssignment(category_id=category.id, product_type="продукты")
        ],
    )

    stored = await CategoryRepository(session).get_for_spreadsheet(category.id, spreadsheet.id)
    assert stored is not None
    assert stored.product_types == ["продукты"]

    targets = {
        task.target
        for task in await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    }
    assert SheetTarget.CATEGORIES in targets


async def test_default_expense_category_never_learns_product_types(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Корзина «НеопределенныеТраты» типов не получает никогда.

    В неё складывается всё, что не удалось разложить. Обучись она на своём
    содержимом — начала бы притягивать к себе следующие чеки.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    basket = await factories.create_category(
        session,
        spreadsheet,
        title=constants.DEFAULT_EXPENSE_CATEGORY,
        kind=CategoryKind.EXPENSE,
    )
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and basket.id is not None and source.id is not None

    await check_service.commit_check(
        spreadsheet.id,
        source_id=source.id,
        items=[
            CheckItem(
                product_name="нечто",
                product_type="странное",
                category_id=basket.id,
                amount=Decimal("10.00"),
            )
        ],
        new_product_types=[
            ProductTypeAssignment(category_id=basket.id, product_type="странное")
        ],
    )

    stored = await CategoryRepository(session).get_for_spreadsheet(basket.id, spreadsheet.id)
    assert stored is not None
    assert stored.product_types == []


async def test_inactive_category_still_accepts_check_item(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Скрытая категория не валит запись всего чека.

    `INACTIVE` означает «не подсказывать», а не «удалена». Позиция, разложенная в
    неё до того, как её скрыли, должна записаться.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Старая")
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    categories = CategoryRepository(session)
    hidden = await categories.update(category.model_copy(update={"status": EntityStatus.INACTIVE}))
    assert hidden is not None and hidden.status is EntityStatus.INACTIVE
    await session.commit()

    records = await check_service.commit_check(
        spreadsheet.id,
        source_id=source.id,
        items=[
            CheckItem(product_name="товар", category_id=category.id, amount=Decimal("15.00"))
        ],
    )
    assert [record.category_id for record in records] == [category.id]


async def test_item_without_product_type_is_not_cached(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Позиция без типа не попадает в кэш: кэшировать нечего."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None and source.id is not None

    await check_service.commit_check(
        spreadsheet.id,
        source_id=source.id,
        items=[
            CheckItem(product_name="загадка", category_id=category.id, amount=Decimal("1.00"))
        ],
    )

    assert await CashedRecordRepository(session).get(spreadsheet.id, "загадка") is None


async def test_alien_category_aborts_whole_check(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Категория чужого документа — 404, и ни одна позиция не записана."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    own = await factories.create_category(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    stranger = await factories.create_spreadsheet(session, ready=True)
    alien = await factories.create_category(session, stranger)
    await session.commit()
    assert spreadsheet.id is not None and own.id is not None
    assert source.id is not None and alien.id is not None

    with pytest.raises(NotFoundError):
        await check_service.commit_check(
            spreadsheet.id,
            source_id=source.id,
            items=[
                CheckItem(product_name="первый", category_id=own.id, amount=Decimal("1.00")),
                CheckItem(product_name="второй", category_id=alien.id, amount=Decimal("2.00")),
            ],
        )
    # Первая позиция к этому моменту уже была добавлена в сессию, поэтому
    # существенно именно то, что после откатa её в базе нет: чек записывается
    # целиком или никак.
    await session.rollback()

    written = await session.scalar(
        select(func.count())
        .select_from(RecordORM)
        .where(RecordORM.spreadsheet_id == spreadsheet.id)
    )
    assert written == 0


async def test_delete_from_queue_of_unknown_check(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Пропустить чек, которого нет, — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    with pytest.raises(NotFoundError):
        await check_service.delete_from_queue(spreadsheet.id, 12345)
