"""Тесты ограничений схемы.

Проверяют не поведение репозиториев, а то, что БД сама не даёт выразить
недопустимое состояние. Каждое ограничение здесь заменяет проверку, которую в
старой версии писали руками в сервисах — и местами забывали.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import CategoryKind, CheckKind
from api.orm.category import CategoryORM
from api.orm.category_association import CategoryAssociationORM
from api.orm.record import RecordORM
from api.orm.sheet_sync_task import SheetSyncTaskORM
from api.orm.spreadsheet import SpreadsheetORM
from api.orm.transfer import TransferORM
from api.orm.user import UserORM
from tests import factories

pytestmark = pytest.mark.usefixtures("clean_db")


async def test_server_version_supports_nulls_not_distinct(session: AsyncSession) -> None:
    """Схеме нужен PostgreSQL 15 и новее: без него схлопывание очереди не работает."""
    version = await session.scalar(text("SHOW server_version_num"))
    assert int(version or 0) >= 150000


async def test_record_cannot_reference_foreign_category(session: AsyncSession) -> None:
    """Операция не может сослаться на категорию из чужого документа.

    Составной внешний ключ `(category_id, spreadsheet_id)` делает это состояние
    невыразимым. Раньше проверку писали в каждом сервисе руками.
    """
    mine = await factories.create_spreadsheet(session)
    other = await factories.create_spreadsheet(session)
    my_period = await factories.create_period(session, mine)
    my_source = await factories.create_source(session, mine)
    foreign_category = await factories.create_category(session, other)
    await session.commit()

    session.add(
        RecordORM(
            spreadsheet_id=mine.id,
            period_id=my_period.id,
            category_id=foreign_category.id,
            source_id=my_source.id,
            amount=Decimal("-1.00"),
            added_at=my_period.start_date,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_duplicate_telegram_id_is_rejected(session: AsyncSession) -> None:
    """Повторный /start не создаёт второго пользователя.

    Раньше уникальности не было: возникала вторая пара «пользователь + документ»,
    и какой из документов считался текущим, определял порядок строк в куче
    Postgres — то есть он менялся после каждого VACUUM.
    """
    await factories.create_user(session, telegram_id=777)
    await session.commit()

    session.add(UserORM(telegram_id=777))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_one_user_cannot_own_two_spreadsheets(session: AsyncSession) -> None:
    """Один пользователь — одна учётная таблица."""
    user = await factories.create_user(session)
    await factories.create_spreadsheet(session, user=user)
    await session.commit()

    session.add(SpreadsheetORM(user_id=user.id, title="Вторая", reset_day=15))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_category_title_is_unique_case_insensitively(session: AsyncSession) -> None:
    """«Еда» и «еда» — одно и то же название внутри документа."""
    spreadsheet = await factories.create_spreadsheet(session)
    await factories.create_category(session, spreadsheet, title="Еда", associations=["еда"])
    await session.commit()

    session.add(
        CategoryORM(spreadsheet_id=spreadsheet.id, kind=CategoryKind.EXPENSE, title="еда")
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleted_category_frees_its_title(session: AsyncSession) -> None:
    """После мягкого удаления название снова свободно.

    Ради этого уникальный индекс частичный: обычный `UNIQUE` навсегда запретил
    бы завести одноимённую категорию заново.
    """
    from api.core.period import now_in_timezone
    from api.repositories.category_repository import CategoryRepository

    spreadsheet = await factories.create_spreadsheet(session)
    first = await factories.create_category(
        session, spreadsheet, title="Еда", associations=["еда"]
    )
    await session.commit()

    assert first.id is not None
    await CategoryRepository(session).soft_delete(
        first.id, at=now_in_timezone(spreadsheet.timezone)
    )
    await session.commit()

    revived = await factories.create_category(
        session, spreadsheet, title="Еда", associations=["еда2"]
    )
    await session.commit()
    assert revived.id != first.id


async def test_alias_is_unique_within_spreadsheet(session: AsyncSession) -> None:
    """Один псевдоним не может принадлежать двум категориям одного документа.

    Именно поэтому псевдонимы вынесены из массива в таблицу: раньше уникальность
    проверял только Python при разборе листа, и подбор молча возвращал последнее
    совпадение.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await factories.create_category(session, spreadsheet, title="Еда", associations=["продукты"])
    second = await factories.create_category(
        session, spreadsheet, title="Кафе", associations=["кафе"]
    )
    await session.commit()

    session.add(
        CategoryAssociationORM(
            spreadsheet_id=spreadsheet.id,
            category_id=second.id,
            alias="продукты",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_alias_must_be_lowercase(session: AsyncSession) -> None:
    """Ненормализованный псевдоним не проходит в обход сервиса."""
    spreadsheet = await factories.create_spreadsheet(session)
    category = await factories.create_category(session, spreadsheet, associations=[])
    await session.commit()

    session.add(
        CategoryAssociationORM(
            spreadsheet_id=spreadsheet.id,
            category_id=category.id,
            alias="ПРОДУКТЫ",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_transfer_amount_must_be_positive(session: AsyncSession) -> None:
    """Отрицательная сумма перевода отвергается.

    Прежняя схема принимала знак от пользователя, и `/transfer -1000 А Б` тихо
    переводил деньги в обратную сторону.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    first = await factories.create_source(session, spreadsheet, title="Карта")
    second = await factories.create_source(session, spreadsheet, title="Нал")
    await session.commit()

    session.add(
        TransferORM(
            spreadsheet_id=spreadsheet.id,
            period_id=period.id,
            from_source_id=first.id,
            to_source_id=second.id,
            amount=Decimal("-1000.00"),
            added_at=period.start_date,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_transfer_to_itself_is_rejected(session: AsyncSession) -> None:
    """Перевод на тот же счёт запрещён на уровне БД."""
    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    source = await factories.create_source(session, spreadsheet)
    await session.commit()

    session.add(
        TransferORM(
            spreadsheet_id=spreadsheet.id,
            period_id=period.id,
            from_source_id=source.id,
            to_source_id=source.id,
            amount=Decimal("100.00"),
            added_at=period.start_date,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_reset_day_outside_range_is_rejected_by_database(session: AsyncSession) -> None:
    """День сброса 31 не проходит: 31 февраля не существует."""
    user = await factories.create_user(session)
    await session.commit()

    session.add(SpreadsheetORM(user_id=user.id, title="Тест", reset_day=31))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_period_target_requires_period(session: AsyncSession) -> None:
    """Задача на лист операций обязана нести период."""
    from api.enums import SheetTarget

    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    session.add(
        SheetSyncTaskORM(
            spreadsheet_id=spreadsheet.id,
            target=SheetTarget.OPERATIONS,
            period_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_non_period_target_must_not_carry_period(session: AsyncSession) -> None:
    """Задача на лист категорий не может нести период.

    Условие двустороннее намеренно. Односторонняя формулировка пропустила бы
    такую строку: она не совпала бы по ключу с нормальной задачей CATEGORIES,
    не схлопнулась бы и осталась висеть навсегда.
    """
    from api.enums import SheetTarget

    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    await session.commit()

    session.add(
        SheetSyncTaskORM(
            spreadsheet_id=spreadsheet.id,
            target=SheetTarget.CATEGORIES,
            period_id=period.id,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleting_spreadsheet_removes_everything(session: AsyncSession) -> None:
    """Удаление документа вычищает все связанные данные и не падает.

    Каскады идут в неопределённом порядке, поэтому составные внешние ключи
    объявлены отложенными: проверка выполняется один раз в конце транзакции,
    когда удалено уже всё. В старой схеме `records.category` был NOT NULL с
    `ON DELETE SET NULL`, и удаление документа падало на нарушении NOT NULL.
    """
    from sqlalchemy import delete, func, select

    from api.enums import SheetTarget
    from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository

    spreadsheet = await factories.create_spreadsheet(session)
    period = await factories.create_period(session, spreadsheet)
    category = await factories.create_category(session, spreadsheet)
    first = await factories.create_source(session, spreadsheet, title="Карта")
    second = await factories.create_source(session, spreadsheet, title="Нал")
    await factories.create_record(
        session, spreadsheet, period, category, first, amount=Decimal("-10.00")
    )
    await factories.create_transfer(
        session, spreadsheet, period, first, second, amount=Decimal("50.00")
    )
    assert spreadsheet.id is not None
    await SheetSyncTaskRepository(session).enqueue(
        spreadsheet.id, SheetTarget.OPERATIONS, period.id
    )
    await session.commit()

    await session.execute(delete(SpreadsheetORM).where(SpreadsheetORM.id == spreadsheet.id))
    await session.commit()

    for orm_type in (RecordORM, TransferORM, CategoryORM, CategoryAssociationORM, SheetSyncTaskORM):
        total = await session.scalar(select(func.count()).select_from(orm_type))
        assert total == 0, f"остались строки в {orm_type.__tablename__}"


async def test_period_start_is_unique_per_spreadsheet(session: AsyncSession) -> None:
    """Два периода с одним началом создать нельзя — на этом стоит ролловер."""
    from api.orm.period import PeriodORM

    spreadsheet = await factories.create_spreadsheet(session)
    await factories.create_period(session, spreadsheet, day=date(2026, 7, 20))
    await session.commit()

    session.add(
        PeriodORM(
            spreadsheet_id=spreadsheet.id,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 8, 15),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_same_check_cannot_be_saved_twice(session: AsyncSession) -> None:
    """Повторный скан того же чека не создаёт второй строки.

    Уникальность стоит на `(spreadsheet_id, kind, external_key)`. Содержимое
    ключа вычисляет парсер формата, поэтому БД не знает ни про ФН, ни про ФД,
    ни про ФП — и всё же дубль в ней невыразим.
    """
    from api.orm.check import CheckORM

    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    fetched_at = datetime(2026, 7, 25, 15, 7, tzinfo=UTC)
    for _ in range(2):
        session.add(
            CheckORM(
                spreadsheet_id=spreadsheet.id,
                kind=CheckKind.RU_FNS,
                qr_raw="t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp=698610272&n=1",
                external_key="7384440901402798:145:698610272",
                raw_payload={"code": 1},
                fetched_at=fetched_at,
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()
