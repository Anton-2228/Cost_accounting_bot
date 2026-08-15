"""Тесты мапперов ORM ↔ domain."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from api.domain.category import Category
from api.domain.record import Record
from api.domain.sheet_sync_task import SheetSyncTask
from api.enums import CategoryKind, SheetTarget
from api.mappers.category_mapper import CategoryMapper
from api.mappers.record_mapper import RecordMapper
from api.mappers.sheet_sync_task_mapper import SheetSyncTaskMapper


def test_to_orm_does_not_set_database_managed_fields() -> None:
    """Маппер не выставляет id и таймстемпы: ими управляет БД."""
    orm = RecordMapper().to_orm(
        Record(
            id=42,
            spreadsheet_id=1,
            period_id=2,
            category_id=3,
            source_id=4,
            amount=Decimal("-10.00"),
            added_at=date(2026, 7, 20),
            created_at=datetime(2020, 1, 1),
        )
    )

    assert orm.id is None
    assert orm.created_at is None
    assert orm.updated_at is None


def test_category_children_become_orm_rows() -> None:
    """Псевдонимы и типы товаров превращаются в дочерние строки."""
    orm = CategoryMapper().to_orm(
        Category(
            spreadsheet_id=7,
            kind=CategoryKind.EXPENSE,
            title="Еда",
            associations=["Продукты", "еда"],
            product_types=["молочное"],
        )
    )

    assert [row.alias for row in orm.association_rows] == ["еда", "продукты"]
    assert [row.product_type for row in orm.product_type_rows] == ["молочное"]
    # spreadsheet_id проставляется явно: составной внешний ключ требует его.
    assert {row.spreadsheet_id for row in orm.association_rows} == {7}


def test_sync_task_timestamps_come_from_database() -> None:
    """Метки времени очереди ставит БД, а не процесс.

    Иначе задачи из разных процессов сравнивались бы по разным часам, и условие
    удаления по `requested_at` перестало бы быть надёжным.
    """
    orm = SheetSyncTaskMapper().to_orm(
        SheetSyncTask(spreadsheet_id=1, target=SheetTarget.CATEGORIES)
    )

    assert orm.requested_at is None
    assert orm.next_attempt_at is None
