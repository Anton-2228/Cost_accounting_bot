"""Фоновый повтор отложенных чеков."""

from __future__ import annotations

import asyncio
import contextlib

from checks_service import constants
from checks_service.logging import get_logger
from checks_service.services.check_intake import CheckIntakeService

logger = get_logger(__name__)


class PendingRetryLoop:
    """Периодически зовёт :meth:`CheckIntakeService.retry_due`.

    Живёт здесь, а не в api рядом с остальными циклами: ходить во внешний
    сервис умеют только фетчеры, а они — в этом сервисе. Api отвечает за учёт:
    что пора повторить, кто сейчас спрашивает, когда спросить снова.

    Интервал короткий, а паузы между попытками — длинные: их назначает api, и
    проход, которому нечего делать, стоит один запрос. Сон прерываемый, поэтому
    выключение контейнера не ждёт истечения интервала.
    """

    def __init__(
        self,
        intake: CheckIntakeService,
        *,
        interval_seconds: float = constants.PENDING_RETRY_INTERVAL_SECONDS,
    ) -> None:
        self._intake = intake
        self._interval = interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Запускает цикл, не блокируя вызывающего."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="pending-retry-loop")
        logger.info("Повтор отложенных чеков запущен, интервал %s с", self._interval)

    async def stop(self) -> None:
        """Просит цикл остановиться и дожидается конца текущего прохода."""
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Повтор отложенных чеков остановлен")

    async def _loop(self) -> None:
        """Проход → прерываемый сон → проход."""
        while not self._stop.is_set():
            try:
                added = await self._intake.retry_due()
                if added:
                    logger.info("Фоном добавлено отложенных чеков: %s", added)
            except asyncio.CancelledError:
                # Всегда первым: иначе остановка приложения повисла бы на цикле.
                raise
            except Exception:
                # Цикл не должен умирать ни от одной ошибки: недоступное api
                # обычно возвращается само, а отложенные чеки подождут.
                logger.exception("Проход повтора отложенных чеков не удался — продолжаем")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except TimeoutError:
                continue
