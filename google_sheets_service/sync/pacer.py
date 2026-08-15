"""Прерываемая пауза между задачами."""

from __future__ import annotations

import asyncio
import contextlib
import random


class Pacer:
    """Пауза между задачами тика, прерываемая при остановке сервиса.

    Пауза стоит **между задачами**, а не между тиками. Квота Google — шестьдесят
    запросов в минуту на проект, и пачка из двадцати задач, выполненная подряд,
    выжгла бы её целиком, после чего весь тик ушёл бы в повторы. Разнесённая по
    задачам пауза размазывает нагрузку и делает расход предсказуемым.

    Ждать приходится не `sleep`, а событие остановки с таймаутом: остановка
    сервиса дожидается конца текущего тика, и обычный сон задержал бы её на
    сумму всех оставшихся пауз.
    """

    def __init__(
        self,
        *,
        interval_seconds: float,
        jitter_seconds: float = 0.0,
        stop: asyncio.Event,
    ) -> None:
        self._interval = interval_seconds
        self._jitter = jitter_seconds
        self._stop = stop

    async def pause(self) -> None:
        """Ждёт интервал с джиттером или до сигнала остановки."""
        if self._interval <= 0 or self._stop.is_set():
            return
        delay = self._interval + random.uniform(0, self._jitter)  # noqa: S311
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
