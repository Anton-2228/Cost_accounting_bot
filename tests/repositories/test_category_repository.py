"""Тесты репозитория категорий: псевдонимы, типы товаров, подбор."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.period import now_in_timezone
from api.enums import CategoryKind
from api.repositories.category_repository import CategoryRepository
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_associations_are_normalized_and_sorted(session: AsyncSession) -> None:
    """Псевдонимы приводятся к нижнему регистру, дедуплицируются и сортируются.

    Сортировка не косметика: раньше набор дедуплицировался через `set()`, а хеш
    строк рандомизирован при каждом запуске процесса — лист `Categories`
    перетасовывался при каждой синхронизации.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    category = await factories.create_category(
        session,
        spreadsheet,
        title="Еда",
        associations=["Продукты", "  еда  ", "продукты", "кафе"],
    )
    await session.commit()

    assert category.id is not None
    stored = await CategoryRepository(session).get_by_id(category.id)
    assert stored is not None
    assert stored.associations == ["еда", "кафе", "продукты"]


async def test_adding_one_alias_does_not_break_on_unique_key(session: AsyncSession) -> None:
    """Добавление псевдонима к существующему набору проходит.

    Наивная реализация — переприсвоить коллекцию и положиться на delete-orphan —
    падает: SQLAlchemy в одном flush выдаёт INSERT раньше DELETE, и вставка
    неизменившегося значения натыкается на ещё живую старую строку.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    category = await factories.create_category(
        session, spreadsheet, title="Еда", associations=["еда", "продукты"]
    )
    await session.commit()

    assert category.id is not None
    updated = await CategoryRepository(session).replace_associations(
        category.id, ["еда", "продукты", "кафе"]
    )
    await session.commit()

    assert updated is not None
    assert updated.associations == ["еда", "кафе", "продукты"]


async def test_replacing_associations_drops_removed_ones(session: AsyncSession) -> None:
    """Выпавшие псевдонимы исчезают и освобождают имя."""
    spreadsheet = await factories.create_spreadsheet(session)
    first = await factories.create_category(
        session, spreadsheet, title="Еда", associations=["еда", "продукты"]
    )
    second = await factories.create_category(
        session, spreadsheet, title="Кафе", associations=["кафе"]
    )
    await session.commit()

    assert first.id is not None
    assert second.id is not None
    repository = CategoryRepository(session)

    await repository.replace_associations(first.id, ["еда"])
    await session.commit()
    # «продукты» освободились и теперь доступны другой категории.
    updated = await repository.replace_associations(second.id, ["кафе", "продукты"])
    await session.commit()

    assert updated is not None
    assert updated.associations == ["кафе", "продукты"]


async def test_find_by_association_is_unambiguous(session: AsyncSession) -> None:
    """Подбор по псевдониму возвращает ровно одну категорию."""
    spreadsheet = await factories.create_spreadsheet(session)
    food = await factories.create_category(
        session, spreadsheet, title="Еда", associations=["продукты"]
    )
    await factories.create_category(session, spreadsheet, title="Транспорт", associations=["метро"])
    await session.commit()

    assert spreadsheet.id is not None
    repository = CategoryRepository(session)

    found = await repository.find_by_association(spreadsheet.id, "ПРОДУКТЫ")
    assert found is not None
    assert found.id == food.id
    assert await repository.find_by_association(spreadsheet.id, "кино") is None


async def test_find_by_association_ignores_other_spreadsheets(session: AsyncSession) -> None:
    """Псевдоним чужого документа не находится."""
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    await factories.create_category(session, other, title="Еда", associations=["продукты"])
    await session.commit()

    assert mine.id is not None
    assert await CategoryRepository(session).find_by_association(mine.id, "продукты") is None


async def test_product_type_cannot_belong_to_two_categories(session: AsyncSession) -> None:
    """Один тип товара закреплён ровно за одной категорией.

    Иначе раскладка позиций чека зависела бы от порядка обработки.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await factories.create_category(
        session, spreadsheet, title="Еда", associations=["еда"], product_types=["молочное"]
    )
    other = await factories.create_category(
        session, spreadsheet, title="Кафе", associations=["кафе"]
    )
    await session.commit()

    assert other.id is not None
    with pytest.raises(IntegrityError):
        await CategoryRepository(session).add_product_type(other.id, "молочное")
        await session.commit()


async def test_add_product_type_is_idempotent(session: AsyncSession) -> None:
    """Повторное добавление того же типа ничего не меняет."""
    spreadsheet = await factories.create_spreadsheet(session)
    category = await factories.create_category(
        session, spreadsheet, title="Еда", associations=["еда"], product_types=["молочное"]
    )
    await session.commit()

    assert category.id is not None
    repository = CategoryRepository(session)
    updated = await repository.add_product_type(category.id, "МОЛОЧНОЕ")
    await session.commit()

    assert updated is not None
    assert updated.product_types == ["молочное"]


async def test_soft_deleted_category_disappears_from_listing(session: AsyncSession) -> None:
    """Удалённая категория пропадает из выборки, но доступна явным запросом."""
    spreadsheet = await factories.create_spreadsheet(session)
    category = await factories.create_category(session, spreadsheet)
    await session.commit()

    assert spreadsheet.id is not None
    assert category.id is not None
    repository = CategoryRepository(session)
    await repository.soft_delete(category.id, at=now_in_timezone(spreadsheet.timezone))
    await session.commit()

    assert await repository.list_by_spreadsheet(spreadsheet.id) == []
    assert len(await repository.list_by_spreadsheet(spreadsheet.id, include_deleted=True)) == 1


async def test_only_active_filter(session: AsyncSession) -> None:
    """Фильтр по активности отделяет скрытые категории от удалённых."""
    from api.enums import EntityStatus

    spreadsheet = await factories.create_spreadsheet(session)
    active = await factories.create_category(
        session, spreadsheet, title="Еда", associations=["еда"], kind=CategoryKind.EXPENSE
    )
    hidden = await factories.create_category(
        session, spreadsheet, title="Старое", associations=["старое"]
    )
    await session.commit()

    assert hidden.id is not None
    repository = CategoryRepository(session)
    hidden.status = EntityStatus.INACTIVE
    await repository.update(hidden)
    await session.commit()

    assert spreadsheet.id is not None
    only_active = await repository.list_by_spreadsheet(spreadsheet.id, only_active=True)
    assert [item.id for item in only_active] == [active.id]
    assert len(await repository.list_by_spreadsheet(spreadsheet.id)) == 2
