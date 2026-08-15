"""Тесты фонового цикла ролловера.

Проверяется поведение цикла, а не смена месяца: остановка должна прерывать сон
мгновенно, а ошибка внутри прохода не должна убивать цикл — иначе система
однажды перестала бы менять месяц молча.

Интервал во всех тестах заведомо большой. Смысл в этом и есть: если остановка
ждёт истечения интервала, тест не уложится в таймаут.
"""

from __future__ import annotations

import asyncio

import pytest

from api.tasks.rollover_loop import RolloverLoop

_LONG_INTERVAL = 3600


def _loop_with(run_once: object) -> RolloverLoop:
    """Цикл с подменённым проходом. Фабрика сессий не нужна — БД не трогаем."""
    loop = RolloverLoop(session_factory=None, interval_seconds=_LONG_INTERVAL)  # type: ignore[arg-type]
    loop.run_once = run_once  # type: ignore[assignment,method-assign]
    return loop


async def test_stop_interrupts_the_sleep_immediately() -> None:
    """Пока цикл спит между проходами, остановка возвращает управление сразу."""
    ticked = asyncio.Event()
    ticks = 0

    async def run_once() -> int:
        nonlocal ticks
        ticks += 1
        ticked.set()
        return 0

    loop = _loop_with(run_once)
    await loop.start()
    await asyncio.wait_for(ticked.wait(), timeout=2)

    await asyncio.wait_for(loop.stop(), timeout=2)
    assert ticks == 1


async def test_failed_tick_does_not_kill_the_loop() -> None:
    """Ошибка в проходе не выносит цикл: он доживает до сна и ждёт остановки."""
    failed = asyncio.Event()
    attempts = 0

    async def run_once() -> int:
        nonlocal attempts
        attempts += 1
        failed.set()
        raise RuntimeError("база недоступна")

    loop = _loop_with(run_once)
    await loop.start()
    await asyncio.wait_for(failed.wait(), timeout=2)

    task = loop._task
    assert task is not None
    assert not task.done()

    await asyncio.wait_for(loop.stop(), timeout=2)
    assert attempts == 1
    assert loop._task is None


async def test_double_start_creates_one_task() -> None:
    """Повторный запуск не плодит вторую задачу."""
    ticked = asyncio.Event()

    async def run_once() -> int:
        ticked.set()
        return 0

    loop = _loop_with(run_once)
    await loop.start()
    first = loop._task
    await loop.start()
    assert loop._task is first

    await asyncio.wait_for(ticked.wait(), timeout=2)
    await asyncio.wait_for(loop.stop(), timeout=2)


@pytest.mark.parametrize("interval", [60, 900])
async def test_interval_is_configurable(interval: int) -> None:
    """Интервал задаётся снаружи: тесту не нужна минутная пауза продакшена."""
    loop = RolloverLoop(session_factory=None, interval_seconds=interval)  # type: ignore[arg-type]
    assert loop._interval == interval
