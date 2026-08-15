"""Выдача задач очереди листов и приём отчётов о работе (служебное, для gsheets)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants, messages
from api.core.logging import get_logger
from api.db.transaction import commit
from api.domain.sheet_sync_task import SheetSyncTask
from api.enums import NotificationKind
from api.exceptions.base import NotFoundError
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.user_notification_repository import UserNotificationRepository

logger = get_logger(__name__)


class SheetSyncTaskService:
    """Точка входа `google_sheets_service` в очередь.

    Готовность документа здесь не проверяется: именно по задаче `STRUCTURE`
    Google-таблица и создаётся.
    """

    def __init__(
        self,
        session: AsyncSession,
        tasks: SheetSyncTaskRepository,
        notifications: UserNotificationRepository,
    ) -> None:
        self._session = session
        self._tasks = tasks
        self._notifications = notifications

    async def claim(
        self,
        limit: int = constants.SHEET_SYNC_CLAIM_LIMIT,
    ) -> list[SheetSyncTask]:
        """Забирает пачку созревших задач.

        Коммит здесь обязателен и немедленен: `claim` держит строки под
        `FOR UPDATE`, а блокировки живут до конца транзакции. Не закоммитить —
        значит запереть очередь на всё время перерисовки листов.
        """
        claimed = await self._tasks.claim(limit)
        await commit(self._session)
        return claimed

    async def complete(self, task_id: int, requested_at: datetime) -> bool:
        """Отмечает задачу выполненной.

        Возвращает False, если за время работы лист успели изменить снова: тогда
        задача остаётся в очереди и освобождается для следующего захода.
        """
        completed = await self._tasks.complete(task_id, requested_at)
        if not completed:
            await self._tasks.release(task_id)
        await commit(self._session)
        return completed

    async def fail(self, task_id: int, error: str, *, terminal: bool = False) -> None:
        """Возвращает задачу в очередь с паузой и, если пора, зовёт пользователя.

        Пока попыток немного, молчим: недоступность Google обычно проходит сама.
        Но если лист не удаётся обновить раз за разом, пользователь видит
        застывшую таблицу и не понимает почему — с этого момента ему нужно
        сказать.

        Условие уведомления кратное, а не точное равенство: при точном
        совпадении единственный пропущенный отчёт о неудаче (воркер умер, не
        успев его отправить) означал бы, что пользователю не скажут уже никогда.

        Терминальная ошибка — исключение из этого правила: ответ Google не
        изменится сам, и ждать пятой попытки значит молчать полчаса о том, что
        известно с первой.
        """
        task = await self._tasks.fail(task_id, error, terminal=terminal)
        if task is None:
            raise NotFoundError("sheet_sync_task")

        alert_every = constants.SHEET_SYNC_ALERT_ATTEMPTS
        periodic = task.attempts >= alert_every and task.attempts % alert_every == 0
        if terminal or periodic:
            await self._notifications.notify(
                task.spreadsheet_id,
                NotificationKind.SYNC_FAILED,
                messages.sync_terminal(error) if terminal else messages.sync_failed(task.attempts),
            )
        await commit(self._session)
        logger.warning("Задача %s не выполнена (попытка %s): %s", task_id, task.attempts, error)
