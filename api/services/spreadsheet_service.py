"""Жизненный цикл учётной таблицы: создание, доступы, справочники, удаление."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants, messages
from api.core.logging import get_logger
from api.core.period import now_in_timezone, period_bounds
from api.domain.category import Category
from api.domain.source import Source
from api.domain.source_balance import SourceBalance
from api.domain.spreadsheet import Spreadsheet
from api.domain.spreadsheet_access import SpreadsheetAccess
from api.domain.user import User
from api.enums import AccessRole, CategoryKind, NotificationKind, SheetTarget, SyncTaskKind
from api.exceptions.base import ConflictError, NotFoundError
from api.repositories.category_repository import CategoryRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_access_repository import SpreadsheetAccessRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.repositories.user_repository import UserRepository
from api.services._periods import today_for
from api.services.base import BaseSpreadsheetService

logger = get_logger(__name__)


class SpreadsheetService(BaseSpreadsheetService):
    """Создание документа, доступы к нему, чтение справочников и удаление."""

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        users: UserRepository,
        periods: PeriodRepository,
        categories: CategoryRepository,
        sources: SourceRepository,
        accesses: SpreadsheetAccessRepository,
        tasks: SheetSyncTaskRepository,
        notifications: UserNotificationRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._users = users
        self._periods = periods
        self._categories = categories
        self._sources = sources
        self._accesses = accesses
        self._tasks = tasks
        self._notifications = notifications

    # --- чтение ---

    async def get(self, spreadsheet_id: int) -> Spreadsheet:
        """Документ по id."""
        return await self._get(spreadsheet_id)

    async def get_by_telegram_id(self, telegram_id: int) -> Spreadsheet:
        """Документ пользователя телеграма.

        Готовность здесь не проверяется намеренно: именно этим запросом бот
        узнаёт, появился ли уже `google_spreadsheet_id`.
        """
        spreadsheet = await self._spreadsheets.get_by_telegram_id(telegram_id)
        if spreadsheet is None:
            raise NotFoundError("spreadsheet")
        return spreadsheet

    async def list_categories(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Category]:
        """Категории документа.

        `include_deleted` нужен перерисовке архивных листов: удаление категории
        мягкое, а её операции остаются в реестре навсегда. Без удалённых
        категорий в колонке `Category` старого листа неоткуда взять название —
        осталась бы пустая ячейка у операции, которая точно была.
        """
        await self._get_ready(spreadsheet_id)
        return await self._categories.list_by_spreadsheet(
            spreadsheet_id,
            only_active=only_active,
            include_deleted=include_deleted,
        )

    async def list_sources(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Source]:
        """Счета документа.

        `include_deleted` — по той же причине, что и у категорий: колонке
        `Source` архивного реестра нужно название удалённого счёта.
        """
        await self._get_ready(spreadsheet_id)
        return await self._sources.list_by_spreadsheet(
            spreadsheet_id,
            only_active=only_active,
            include_deleted=include_deleted,
        )

    async def list_balances(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
    ) -> list[SourceBalance]:
        """Текущие балансы счетов.

        Баланс не хранится, а считается из начального остатка, операций и
        переводов. Прежняя схема держала `current_balance` колонкой, и любая
        потерянная правка расходилась с реестром навсегда.
        """
        await self._get_ready(spreadsheet_id)
        return await self._sources.balances(spreadsheet_id, only_active=only_active)

    async def list_accesses(self, spreadsheet_id: int) -> list[SpreadsheetAccess]:
        """Все выданные и ожидающие выдачи доступы (служебное, для gsheets)."""
        await self._get(spreadsheet_id)
        return await self._accesses.list_by_spreadsheet(spreadsheet_id)

    async def list_pending_accesses(self, spreadsheet_id: int) -> list[SpreadsheetAccess]:
        """Доступы, которые ещё предстоит выдать (служебное, для gsheets)."""
        await self._get(spreadsheet_id)
        return await self._accesses.list_pending(spreadsheet_id)

    # --- создание ---

    async def create(
        self,
        *,
        telegram_id: int,
        title: str,
        reset_day: int,
        timezone: str = constants.DEFAULT_TIMEZONE,
        email: str | None = None,
    ) -> Spreadsheet:
        """Создаёт документ со всем содержимым одной транзакцией.

        Google-таблицы здесь не появляется: api в Google не ходит. Вместо этого
        ставится задача `STRUCTURE`, а `google_spreadsheet_id` остаётся пустым,
        пока `google_sheets_service` не создаст документ и не пришлёт его id.
        Так операция не может завершиться наполовину: прежний код создавал
        таблицу в Google **до** записи в БД, и падение БД оставляло осиротевший
        документ, о котором никто уже не знал.
        """
        user = await self._users.get_by_telegram_id(telegram_id)
        if user is None:
            user = await self._users.add(User(telegram_id=telegram_id))
        else:
            assert user.id is not None
            if await self._spreadsheets.get_by_user_id(user.id) is not None:
                raise ConflictError(
                    "У пользователя уже есть таблица",
                    details={"reason": "spreadsheet_exists"},
                )

        assert user.id is not None
        spreadsheet = await self._spreadsheets.add(
            Spreadsheet(
                user_id=user.id,
                title=title,
                reset_day=reset_day,
                timezone=timezone,
            )
        )
        assert spreadsheet.id is not None

        start_date, end_date = period_bounds(today_for(spreadsheet), reset_day)
        await self._periods.ensure(spreadsheet.id, start_date, end_date)

        for kind, category_title in (
            (CategoryKind.INCOME, constants.DEFAULT_INCOME_CATEGORY),
            (CategoryKind.EXPENSE, constants.DEFAULT_EXPENSE_CATEGORY),
        ):
            await self._categories.add(
                Category(
                    spreadsheet_id=spreadsheet.id,
                    kind=kind,
                    title=category_title,
                    associations=[category_title],
                )
            )

        if email is not None:
            await self._accesses.add(
                SpreadsheetAccess(
                    spreadsheet_id=spreadsheet.id,
                    email=email,
                    role=AccessRole.WRITER,
                )
            )

        await self._tasks.enqueue(spreadsheet.id, SheetTarget.STRUCTURE)
        await self._commit()
        logger.info("Создан документ %s пользователя %s", spreadsheet.id, telegram_id)
        return spreadsheet

    # --- служебное: связь с google_sheets_service ---

    async def set_google_id(self, spreadsheet_id: int, google_spreadsheet_id: str) -> Spreadsheet:
        """Привязывает созданный Google-документ к учётной таблице.

        Идемпотентно для того же самого id: `google_sheets_service` мог успеть
        создать документ и потерять ответ. Попытка привязать **другой** документ
        отвергается — данные уже связаны с первым, и подмена оставила бы
        пользователя с таблицей, в которой ничего нет.
        """
        spreadsheet = await self._get(spreadsheet_id)
        if spreadsheet.google_spreadsheet_id == google_spreadsheet_id:
            return spreadsheet
        if spreadsheet.google_spreadsheet_id is not None:
            raise ConflictError(
                "К документу уже привязана другая Google-таблица",
                details={"reason": "google_id_already_set"},
            )

        updated = await self._spreadsheets.set_google_spreadsheet_id(
            spreadsheet_id, google_spreadsheet_id
        )
        if updated is None:
            raise NotFoundError("spreadsheet")
        await self._notifications.notify(
            spreadsheet_id,
            NotificationKind.TABLE_READY,
            messages.table_ready(google_spreadsheet_id),
        )
        await self._enqueue_full_redraw(spreadsheet_id)
        await self._commit()
        return updated

    async def mark_access_granted(self, spreadsheet_id: int, access_id: int) -> None:
        """Отмечает доступ выданным (служебное, для gsheets)."""
        spreadsheet = await self._get(spreadsheet_id)
        assert spreadsheet.id is not None
        granted = await self._accesses.mark_granted(
            access_id, at=now_in_timezone(spreadsheet.timezone)
        )
        if not granted:
            raise NotFoundError("access")
        await self._commit()

    async def mark_access_failed(self, spreadsheet_id: int, access_id: int) -> None:
        """Google отказался выдать доступ на эту почту (служебное, для gsheets).

        Запись удаляется, а не остаётся ждать: `granted_at IS NULL` означает
        «выдать предстоит», и неверный адрес попадал бы в каждую последующую
        сверку скелета, порождая по уведомлению на каждую. Пользователь добавит
        почту заново — уже правильную.
        """
        await self._get(spreadsheet_id)
        access = await self._accesses.get_by_id(access_id)
        if access is None or access.spreadsheet_id != spreadsheet_id:
            raise NotFoundError("access")

        await self._accesses.delete(access_id)
        await self._notifications.notify(
            spreadsheet_id,
            NotificationKind.SYNC_FAILED,
            messages.access_failed(access.email),
        )
        await self._commit()
        logger.warning("Доступ %s документа %s не выдан", access_id, spreadsheet_id)

    # --- изменение ---

    async def add_access(
        self,
        spreadsheet_id: int,
        email: str,
        role: AccessRole = AccessRole.WRITER,
    ) -> SpreadsheetAccess:
        """Добавляет доступ к документу и просит gsheets его выдать."""
        await self._get_ready(spreadsheet_id)
        if await self._accesses.get_by_email(spreadsheet_id, email) is not None:
            raise ConflictError(
                "Доступ для этой почты уже добавлен",
                details={"reason": "access_exists"},
            )

        access = await self._accesses.add(
            SpreadsheetAccess(spreadsheet_id=spreadsheet_id, email=email, role=role)
        )
        await self._tasks.enqueue(spreadsheet_id, SheetTarget.STRUCTURE)
        await self._commit()
        return access

    async def request_import(self, spreadsheet_id: int) -> None:
        """Просит вчитать правки листов `Categories` и `Bills` (команда `/sync`).

        Бот не имеет доступа к Google API, поэтому просьба едет в
        `google_sheets_service` единственным доступным каналом — очередью.
        Результат вернётся асинхронно: ошибка разбора попадёт в уведомления.
        """
        await self._get_ready(spreadsheet_id)
        keys: list[TaskKey] = [
            (spreadsheet_id, SyncTaskKind.IMPORT, SheetTarget.CATEGORIES, None),
            (spreadsheet_id, SyncTaskKind.IMPORT, SheetTarget.BILLS, None),
        ]
        await self._tasks.enqueue_many(keys)
        await self._commit()

    async def delete(self, spreadsheet_id: int) -> None:
        """Удаляет документ вместе с пользователем и всем содержимым.

        Google-таблица остаётся у пользователя: она — его архив, и удалять её
        молча система права не имеет. Так было и раньше.
        """
        spreadsheet = await self._get(spreadsheet_id)
        await self._users.delete(spreadsheet.user_id)
        await self._commit()
        logger.info("Удалён документ %s", spreadsheet_id)

    # --- служебное ---

    async def _enqueue_full_redraw(self, spreadsheet_id: int) -> None:
        """Ставит перерисовку всех листов документа.

        Вызывается, когда Google-таблица только что появилась: к этому моменту
        в БД уже есть категории, а возможно и операции, сделанные до её
        создания.
        """
        keys: list[TaskKey] = [
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.CATEGORIES, None),
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None),
        ]
        for period in await self._periods.list_open(spreadsheet_id):
            keys += [
                (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period.id),
                (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.STATISTICS, period.id),
            ]
        await self._tasks.enqueue_many(keys)
