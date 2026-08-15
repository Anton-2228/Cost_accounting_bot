"""Фоновый цикл смены учётного месяца."""

from __future__ import annotations

import asyncio
import contextlib

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import constants
from api.core.logging import get_logger
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.rollover_service import RolloverService

logger = get_logger(__name__)


class RolloverLoop:
    """Периодически зовёт :class:`RolloverService` на своей сессии.

    Своя сессия, а не запросная: у фоновой задачи нет запроса, а держать
    соединение из пула между проходами незачем — проход занимает миллисекунды.

    Сон прерываемый (`asyncio.wait_for` по событию остановки), поэтому
    выключение контейнера не ждёт истечения интервала.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        interval_seconds: int = constants.ROLLOVER_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._interval = interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Запускает цикл, не блокируя вызывающего."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="rollover-loop")
        logger.info("Ролловер запущен, интервал %s с", self._interval)

    async def stop(self) -> None:
        """Просит цикл остановиться и дожидается конца текущего прохода."""
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Ролловер остановлен")

    async def _loop(self) -> None:
        """Проход → прерываемый сон → проход."""
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                # Всегда первым: иначе остановка приложения повисла бы на цикле.
                raise
            except Exception:
                # Цикл не должен умирать ни от одной ошибки: смена месяца — то,
                # без чего система перестаёт работать целиком, а причина сбоя
                # (недоступная БД) обычно проходит сама.
                logger.exception("Проход ролловера не удался — продолжаем")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except TimeoutError:
                continue

    async def run_once(self) -> int:
        """Один проход по всем документам. Возвращает число изменённых."""
        async with self._session_factory() as session:
            service = RolloverService(
                session,
                SpreadsheetRepository(session),
                periods=PeriodRepository(session),
                tasks=SheetSyncTaskRepository(session),
                notifications=UserNotificationRepository(session),
            )
            return await service.run_once()
