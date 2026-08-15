"""Фоновый цикл и пауза между задачами."""

from __future__ import annotations

import asyncio

from google_sheets_service.scheduler import BackgroundScheduler
from google_sheets_service.sync.engine import TickReport
from google_sheets_service.sync.pacer import Pacer


class _StubEngine:
    """Движок-заглушка: считает проходы и умеет отвечать ошибкой."""

    def __init__(self, *, claimed: int = 0, error: Exception | None = None) -> None:
        self.runs = 0
        self._claimed = claimed
        self._error = error
        self.started = asyncio.Event()

    async def run_once(self) -> TickReport:
        """Считает проход."""
        self.runs += 1
        self.started.set()
        if self._error is not None:
            raise self._error
        return TickReport(claimed=self._claimed)


def _scheduler(engine: _StubEngine, *, interval: float = 60.0) -> BackgroundScheduler:
    """Планировщик над заглушкой, без начальной задержки."""
    return BackgroundScheduler(
        engine=engine,  # type: ignore[arg-type]
        stop=asyncio.Event(),
        interval_seconds=interval,
        initial_delay_seconds=0,
    )


async def test_loop_runs_a_tick() -> None:
    """Цикл выполняет проход."""
    engine = _StubEngine()
    scheduler = _scheduler(engine)

    await scheduler.start()
    await asyncio.wait_for(engine.started.wait(), timeout=1)
    await scheduler.stop()

    assert engine.runs >= 1


async def test_stop_interrupts_the_wait() -> None:
    """Остановка прерывает ожидание, а не ждёт полного интервала.

    Интервал здесь — минута; если бы остановка его дожидалась, тест не уложился
    бы в свой таймаут.
    """
    engine = _StubEngine()
    scheduler = _scheduler(engine, interval=60.0)

    await scheduler.start()
    await asyncio.wait_for(engine.started.wait(), timeout=1)
    await asyncio.wait_for(scheduler.stop(), timeout=1)

    assert engine.runs == 1


async def test_failed_tick_does_not_kill_the_loop() -> None:
    """Ошибка прохода не роняет цикл.

    Иначе единственный сбой Google означал бы, что очередь не разбирается до
    перезапуска контейнера.
    """
    engine = _StubEngine(error=RuntimeError("сломалось"))
    scheduler = _scheduler(engine, interval=0.01)

    await scheduler.start()
    await asyncio.wait_for(engine.started.wait(), timeout=1)
    await asyncio.sleep(0.05)
    await scheduler.stop()

    assert engine.runs >= 2


async def test_pacer_pause_is_interruptible() -> None:
    """Пауза между задачами прерывается сигналом остановки.

    Остановка сервиса дожидается конца текущего прохода, и обычный сон задержал
    бы её на сумму всех оставшихся пауз.
    """
    stop = asyncio.Event()
    pacer = Pacer(interval_seconds=60.0, stop=stop)

    task = asyncio.create_task(pacer.pause())
    await asyncio.sleep(0)
    stop.set()

    await asyncio.wait_for(task, timeout=1)


async def test_pacer_is_noop_without_interval() -> None:
    """Нулевой интервал не заставляет ждать вовсе."""
    await asyncio.wait_for(
        Pacer(interval_seconds=0, stop=asyncio.Event()).pause(), timeout=1
    )
