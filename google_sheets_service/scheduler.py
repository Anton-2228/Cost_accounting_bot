"""Фоновый цикл: периодически запускает проход по очереди."""

from __future__ import annotations

import asyncio
import contextlib

from google_sheets_service.logging import get_logger
from google_sheets_service.sync.engine import SyncEngine

logger = get_logger(__name__)


class BackgroundScheduler:
    """Задача asyncio плюс событие остановки.

    Проходы с работой идут вплотную: паузу держит `Pacer` между задачами, и
    добавлять к ней ещё одну между проходами значило бы задерживать очередь на
    ровном месте. Интервал здесь — нижняя граница пустого прохода: когда
    очередь пуста, `claim` не должен крутиться без передышки.

    Событие остановки общее с `Pacer`: оно прерывает и паузу между задачами, и
    ожидание следующего прохода, поэтому остановка сервиса не ждёт полного
    интервала. Защита от наложения проходов живёт в самом движке.
    """

    def __init__(
        self,
        *,
        engine: SyncEngine,
        stop: asyncio.Event,
        interval_seconds: float,
        initial_delay_seconds: float = 0.0,
    ) -> None:
        self._engine = engine
        self._stop = stop
        self._interval = interval_seconds
        self._initial_delay = initial_delay_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Запускает цикл, не дожидаясь первого прохода."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="gsheets-sync-loop")
        logger.info(
            "Цикл запущен: интервал %.1f с, первый проход через %.1f с",
            self._interval,
            self._initial_delay,
        )

    async def stop(self) -> None:
        """Просит остановиться и дожидается конца текущего прохода.

        Именно дожидается, а не отменяет: отмена посреди `batchUpdate` оставила
        бы задачу забранной, а лист — в неизвестном состоянии.
        """
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Цикл остановлен")

    async def _loop(self) -> None:
        """Ждёт начальную задержку, затем проходит по очереди снова и снова."""
        if await self._sleep(self._initial_delay):
            return

        while not self._stop.is_set():
            did_work = False
            try:
                report = await self._engine.run_once()
                did_work = report.claimed > 0
            except asyncio.CancelledError:
                # Пробрасывается всегда: без этого остановка сервиса повисла бы.
                raise
            except Exception:  # noqa: BLE001 — цикл переживает любую ошибку прохода
                logger.exception("Проход завершился ошибкой, продолжаем")

            # Проход, который что-то сделал, уже выдержал паузы между задачами.
            # Ждать дополнительно незачем — очередь может быть не пуста.
            if did_work:
                continue
            if await self._sleep(self._interval):
                return

    async def _sleep(self, seconds: float) -> bool:
        """Ждёт указанное время. Возвращает True, если попросили остановиться."""
        if seconds <= 0:
            return self._stop.is_set()
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            return False
        return True
