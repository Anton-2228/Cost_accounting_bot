"""Тесты вчитывания листа `Categories`."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.cashed_record import CashedRecord
from api.domain.user_message import UserMessage
from api.enums import CategoryKind, EntityStatus, NotificationKind, SheetTarget
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.category_import_service import CategoryImportService
from tests import factories


def _row(
    category_id: str = "",
    active: str = "1",
    income: str = "0",
    cost: str = "1",
    name: str = "Еда",
    associations: str = "",
    product_types: str = "",
) -> list[str]:
    """Строка листа `Categories`: ID · Active · Income · Cost · Name · Assoc · Types."""
    return [category_id, active, income, cost, name, associations, product_types]


async def test_new_row_creates_category(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Строка без ID создаёт категорию; название всегда попадает в псевдонимы."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await category_import_service.import_rows(
        spreadsheet.id,
        [_row(name="Продукты", associations="еда магазин")],
    )

    assert result.error is None
    assert (result.created, result.updated, result.deleted) == (1, 0, 0)

    categories = await CategoryRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert [category.title for category in categories] == ["Продукты"]
    assert categories[0].associations == ["еда", "магазин", "продукты"]


async def test_swapping_aliases_between_two_categories(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Обмен псевдонимами между двумя категориями проходит.

    Уникальность псевдонима действует на весь документ, поэтому по одной
    категории такая правка неисполнима: вставка нового значения упёрлась бы в
    ещё не удалённое старое. Наборы и пишутся одним заходом — сначала все
    удаления, затем flush, затем все вставки.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    first = await factories.create_category(
        session, spreadsheet, title="Первая", associations=["альфа"]
    )
    second = await factories.create_category(
        session, spreadsheet, title="Вторая", associations=["бета"]
    )
    await session.commit()
    assert spreadsheet.id is not None and first.id is not None and second.id is not None

    result = await category_import_service.import_rows(
        spreadsheet.id,
        [
            _row(str(first.id), name="Первая", associations="бета"),
            _row(str(second.id), name="Вторая", associations="альфа"),
        ],
    )

    assert result.error is None
    categories = CategoryRepository(session)
    stored_first = await categories.get_for_spreadsheet(first.id, spreadsheet.id)
    stored_second = await categories.get_for_spreadsheet(second.id, spreadsheet.id)
    assert stored_first is not None and stored_second is not None
    assert stored_first.associations == ["бета", "первая"]
    assert stored_second.associations == ["альфа", "вторая"]


async def test_cleared_row_deletes_category_and_frees_aliases(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Очищенная строка удаляет категорию, освобождая её имя.

    Псевдонимы снимаются и с удалённой: их уникальность действует независимо от
    `deleted_at`, иначе имя осталось бы занятым навсегда.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(
        session, spreadsheet, title="Лишняя", associations=["лишняя"]
    )
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None

    result = await category_import_service.import_rows(
        spreadsheet.id,
        [
            [str(category.id), "", "", "", "", "", ""],
            _row(name="Новая", associations="лишняя"),
        ],
    )

    assert result.error is None
    assert (result.created, result.deleted) == (1, 1)

    categories = await CategoryRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert [item.title for item in categories] == ["Новая"]
    assert categories[0].associations == ["лишняя", "новая"]


async def test_dropped_product_types_clear_learned_cache(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Выпавший тип товара стирается из кэша «товар → тип».

    Иначе кэш продолжал бы раскладывать будущие чеки по типу, которого больше
    нет ни у одной категории.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(
        session, spreadsheet, title="Еда", product_types=["продукты", "напитки"]
    )
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None

    cache = CashedRecordRepository(session)
    await cache.upsert(
        CashedRecord(spreadsheet_id=spreadsheet.id, product_name="сок", product_type="напитки")
    )
    await cache.upsert(
        CashedRecord(spreadsheet_id=spreadsheet.id, product_name="хлеб", product_type="продукты")
    )
    await session.commit()

    await category_import_service.import_rows(
        spreadsheet.id,
        [_row(str(category.id), name="Еда", product_types="продукты")],
    )

    assert await cache.get(spreadsheet.id, "сок") is None
    assert await cache.get(spreadsheet.id, "хлеб") is not None


async def test_inactive_flag_is_read(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Колонка Active скрывает категорию из подсказок, не удаляя её."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await category_import_service.import_rows(spreadsheet.id, [_row(active="0", name="Скрытая")])

    categories = CategoryRepository(session)
    assert await categories.list_by_spreadsheet(spreadsheet.id, only_active=True) == []
    hidden = await categories.list_by_spreadsheet(spreadsheet.id)
    assert [item.status for item in hidden] == [EntityStatus.INACTIVE]


async def test_broken_sheet_writes_nothing_and_notifies(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Ошибка разбора: в БД ничего, пользователю — отказ с номером строки.

    Лист правится целиком, и применить его половину значит оставить справочник в
    состоянии, которого пользователь не задумывал. Сказать об этом можно только
    уведомлением: в момент разбора HTTP-запроса пользователя уже нет.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await category_import_service.import_rows(
        spreadsheet.id,
        [_row(name="Хорошая"), _row(active="да", name="Плохая")],
    )

    assert result.error == UserMessage(
        code="import_error.flag_invalid", params={"row": 2, "column": "Active"}
    )
    assert (result.created, result.updated, result.deleted) == (0, 0, 0)
    assert await CategoryRepository(session).list_by_spreadsheet(spreadsheet.id) == []

    notifications = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in notifications] == [NotificationKind.IMPORT_ERROR]
    assert (notifications[0].code, notifications[0].params) == (
        "import_error.flag_invalid",
        {
            "row": 2,
            "column": "Active",
        },
    )


async def test_successful_import_confirms_itself(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Прочитанный лист подтверждается уведомлением.

    До сих пор импорт сообщал о себе только ошибкой: `/table_sync` отвечал
    «задачу поставили», и пользователь, поправивший опечатку, не имел способа
    убедиться, что правку увидели.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    await category_import_service.import_rows(spreadsheet.id, [_row(name="Еда")])

    notifications = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in notifications] == [NotificationKind.IMPORT_OK]
    assert notifications[0].params == {"sheet": "Categories"}


async def test_import_that_changes_nothing_still_confirms(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Повторное чтение того же листа подтверждается снова.

    Подтверждение не зависит от счётчиков: пользователь мог править лист,
    передумать и вернуть как было. Молчание в ответ он прочитает как «меня не
    услышали» — ровно та неопределённость, ради которой уведомление и
    заводилось.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    await session.commit()
    assert spreadsheet.id is not None

    result = await category_import_service.import_rows(
        spreadsheet.id, [_row(category_id=str(category.id), name="Еда")]
    )

    assert (result.created, result.deleted) == (0, 0)
    notifications = await UserNotificationRepository(session).list_undelivered(spreadsheet.id)
    assert [item.kind for item in notifications] == [NotificationKind.IMPORT_OK]


async def test_repeated_id_is_rejected(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Один ID в двух строках — ошибка разбора, а не падение импорта.

    Скопированная строка означала бы две несовместимые правки одной записи, а
    «удалить» вместе с «обновить» роняло импорт с KeyError.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Еда")
    await session.commit()
    assert spreadsheet.id is not None and category.id is not None

    result = await category_import_service.import_rows(
        spreadsheet.id,
        [
            [str(category.id), "", "", "", "", "", ""],
            _row(str(category.id), name="Еда"),
        ],
    )

    assert result.error == UserMessage(code="import_error.duplicate_id")


async def test_unknown_id_is_rejected(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """ID из чужой таблицы или опечатка — ошибка разбора.

    Прежний код брал `by_id[int(row[0])]` без проверки и падал с KeyError.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await category_import_service.import_rows(spreadsheet.id, [_row("4242", name="Чужая")])
    assert result.error == UserMessage(code="import_error.unknown_id", params={"row": 1})


async def test_short_rows_are_padded(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Google обрезает хвостовые пустые ячейки — короткая строка не должна падать."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None

    result = await category_import_service.import_rows(spreadsheet.id, [["", "1", "0", "1", "Еда"]])
    assert result.error is None
    assert result.created == 1


async def test_import_marks_dependent_sheets_stale(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Правка справочника устаревает и реестр, и статистику открытого периода.

    В реестре печатается название категории, а строки статистики — это сами
    активные категории.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    period = await factories.create_period(session, spreadsheet)
    await session.commit()
    assert spreadsheet.id is not None and period.id is not None

    await category_import_service.import_rows(spreadsheet.id, [_row(name="Еда")])

    tasks = await SheetSyncTaskRepository(session).list_by_spreadsheet(spreadsheet.id)
    assert {task.target for task in tasks} == {
        SheetTarget.CATEGORIES,
        SheetTarget.OPERATIONS,
        SheetTarget.STATISTICS,
    }
    assert {task.period_id for task in tasks} == {None, period.id}


async def test_import_keeps_the_default_flag(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Переименованная в листе корзина остаётся корзиной.

    `update` переписывает все колонки из доменной модели, и забытый при
    импорте флаг снимался бы с корзины молча, при любой правке листа.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    basket = await factories.create_category(session, spreadsheet, title="Корзина", is_default=True)
    await session.commit()
    assert spreadsheet.id is not None and basket.id is not None

    result = await category_import_service.import_rows(
        spreadsheet.id, [_row(str(basket.id), name="Прочее")]
    )

    assert result.error is None
    stored = await CategoryRepository(session).get_for_spreadsheet(basket.id, spreadsheet.id)
    assert stored is not None
    assert (stored.title, stored.is_default) == ("Прочее", True)


async def _rejected(
    session: AsyncSession,
    service: CategoryImportService,
    row: list[str] | None = None,
    **fields: str,
) -> UserMessage | None:
    """Отказ импорта строки с корзиной; корзина при этом цела."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    basket = await factories.create_category(session, spreadsheet, title="Корзина", is_default=True)
    await session.commit()
    assert spreadsheet.id is not None and basket.id is not None

    sheet_row = row if row is not None else _row(str(basket.id), name="Корзина", **fields)
    if row is not None:
        sheet_row[0] = str(basket.id)
    result = await service.import_rows(spreadsheet.id, [sheet_row])

    stored = await CategoryRepository(session).get_for_spreadsheet(basket.id, spreadsheet.id)
    assert stored is not None
    assert (stored.status, stored.kind, stored.is_default) == (
        EntityStatus.ACTIVE,
        CategoryKind.EXPENSE,
        True,
    )
    return result.error


async def test_default_category_cannot_be_deleted(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Очищенная строка корзины — отказ: неразложенному некуда было бы деться."""
    error = await _rejected(session, category_import_service, row=["", "", "", "", "", "", ""])
    assert error == UserMessage(code="import_error.default_removed", params={"row": 1})


async def test_default_category_cannot_be_deactivated(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Выключенная корзина пропала бы из подсказок, оставшись корзиной."""
    error = await _rejected(session, category_import_service, active="0")
    assert error == UserMessage(code="import_error.default_deactivated", params={"row": 1})


async def test_default_category_cannot_change_kind(
    session: AsyncSession,
    category_import_service: CategoryImportService,
) -> None:
    """Корзина расходов не становится доходной: разбор чека остался бы без неё."""
    error = await _rejected(session, category_import_service, income="1", cost="0")
    assert error == UserMessage(code="import_error.default_kind_changed", params={"row": 1})
