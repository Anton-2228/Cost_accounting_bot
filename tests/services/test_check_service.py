"""Тесты чеков: сохранение сырья, кэш типов и запись разобранного чека."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.domain.check import Check
from api.domain.check_item import CheckItem, ProductTypeAssignment
from api.enums import CategoryKind, CheckKind, EntityStatus, SheetTarget
from api.exceptions.base import ConflictError, NotFoundError
from api.orm.record import RecordORM
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.services.check_service import CheckService
from tests import factories

_QR = "t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp=698610272&n=1"
_KEY = "7384440901402798:145:698610272"
_FETCHED_AT = datetime(2026, 7, 25, 15, 8, tzinfo=UTC)


async def _save(service: CheckService, spreadsheet_id: int, *, key: str = _KEY) -> Check:
    """Сохраняет чек с типовым сырьём ФНС."""
    return await service.save(
        spreadsheet_id,
        kind=CheckKind.RU_FNS,
        qr_raw=_QR,
        external_key=key,
        raw_payload={"code": 1, "data": {"json": {"items": [{"name": "молоко", "sum": 8990}]}}},
        fetched_at=_FETCHED_AT,
    )


async def test_check_is_saved_before_google_table_exists(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Чек сохраняется независимо от готовности таблицы.

    Сканирующему незачем знать, дорисован ли Google-документ: чек полежит и
    дождётся разбора.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    saved = await _save(check_service, spreadsheet.id)
    assert saved.id is not None
    assert [check.external_key for check in await check_service.list_checks(spreadsheet.id)] == [
        _KEY
    ]


async def test_repeated_scan_is_conflict_and_creates_nothing(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Тот же чек второй раз — 409, и вторая строка не появляется."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    assert spreadsheet.id is not None

    await _save(check_service, spreadsheet.id)
    with pytest.raises(ConflictError):
        await _save(check_service, spreadsheet.id)

    assert len(await check_service.list_checks(spreadsheet.id)) == 1


async def test_same_check_in_two_documents(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Чек, добавленный одним документом, не мешает другому.

    В магазин ходят вдвоём, и одна и та же бумажка попадает в две разные
    таблицы. Дедупликация поэтому в пределах документа, а не глобальная.
    """
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    await session.commit()
    assert mine.id is not None and other.id is not None

    await _save(check_service, mine.id)
    await _save(check_service, other.id)

    assert len(await check_service.list_checks(mine.id)) == 1
    assert len(await check_service.list_checks(other.id)) == 1


async def test_commit_writes_whole_check_in_one_transaction(
    session: AsyncSession,
    check_service: CheckService,
) -> None:
    """Позиции, кэш и задачи перерисовки — всё сразу.

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
        check_json="сырой чек",
    )

    assert [record.amount for record in records] == [Decimal("-89.90"), Decimal("-450.00")]

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


async def test_save_into_unknown_spreadsheet(check_service: CheckService) -> None:
    """Чек в несуществующий документ — 404."""
    with pytest.raises(NotFoundError):
        await _save(check_service, 12345)
