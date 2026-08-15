"""Тесты фоновой рассылки уведомлений в бота.

Проверяется договор с ботом, а не текст сообщений: что подтверждается только
принятое, что недоступность бота не теряет очередь и не растягивает проход на
полсотни таймаутов, и что ошибка не убивает цикл.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.enums import NotificationKind
from api.repositories.user_notification_repository import UserNotificationRepository
from api.tasks.notification_loop import NotificationLoop
from tests.factories import create_spreadsheet, create_user

_LONG_INTERVAL = 3600
_NOTIFY_URL = "http://bot:8002/notify"


class _FakeClient:
    """Подмена httpx-клиента: ведёт журнал вызовов и отвечает по сценарию.

    Не наследует настоящий клиент, а повторяет его форму: предмет проверки —
    что и в каком порядке ушло боту, а не работа httpx.
    """

    def __init__(self, *outcomes: int | Exception) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        """Отдаёт следующий исход сценария; по исчерпании — всегда успех."""
        self.calls.append(json)
        outcome = self._outcomes.pop(0) if self._outcomes else 204
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, request=httpx.Request("POST", url))


def _loop(
    session_factory: async_sessionmaker[AsyncSession] | None,
    client: _FakeClient | None = None,
) -> NotificationLoop:
    """Цикл с подменённым HTTP-клиентом: сети в тестах нет."""
    loop = NotificationLoop(
        session_factory,  # type: ignore[arg-type]
        notify_url=_NOTIFY_URL,
        interval_seconds=_LONG_INTERVAL,
    )
    loop._client = client  # type: ignore[assignment]
    return loop


async def test_accepted_notification_is_marked_delivered(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Бот ответил 2xx — сообщение подтверждено и второй раз не уйдёт."""
    async with session_factory() as session:
        user = await create_user(session, telegram_id=777)
        spreadsheet = await create_spreadsheet(session, user=user, ready=True)
        assert spreadsheet.id is not None
        await UserNotificationRepository(session).notify(
            spreadsheet.id, NotificationKind.TABLE_READY, "Таблица готова"
        )
        await session.commit()

    client = _FakeClient(204)
    loop = _loop(session_factory, client)

    assert await loop.run_once() == 1
    assert client.calls[0]["telegram_id"] == 777
    assert client.calls[0]["text"] == "Таблица готова"
    assert client.calls[0]["kind"] == NotificationKind.TABLE_READY.value

    # Второй проход не находит работы: подтверждённое из очереди ушло.
    assert await loop.run_once() == 0
    assert len(client.calls) == 1


async def test_rejected_notification_stays_in_the_queue(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Не-2xx считается временной неудачей: сообщение остаётся и повторится."""
    async with session_factory() as session:
        spreadsheet = await create_spreadsheet(session, ready=True)
        assert spreadsheet.id is not None
        await UserNotificationRepository(session).notify(
            spreadsheet.id, NotificationKind.IMPORT_ERROR, "В категориях в 5 строке беда"
        )
        await session.commit()

    client = _FakeClient(500, 204)
    loop = _loop(session_factory, client)

    assert await loop.run_once() == 0
    assert await loop.run_once() == 1
    assert len(client.calls) == 2


async def test_unreachable_bot_stops_the_tick(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Сетевая ошибка обрывает проход целиком.

    Бот недоступен для всех сообщений сразу, и продолжать значило бы сложить
    столько таймаутов, сколько строк в очереди.
    """
    async with session_factory() as session:
        spreadsheet = await create_spreadsheet(session, ready=True)
        assert spreadsheet.id is not None
        repository = UserNotificationRepository(session)
        for number in range(3):
            await repository.notify(spreadsheet.id, NotificationKind.ROLLOVER, str(number))
        await session.commit()

    client = _FakeClient(httpx.ConnectError("бот лежит"))
    loop = _loop(session_factory, client)

    assert await loop.run_once() == 0
    assert len(client.calls) == 1

    # Бот поднялся — та же очередь уходит целиком и в прежнем порядке.
    recovered = _FakeClient()
    loop = _loop(session_factory, recovered)
    assert await loop.run_once() == 3
    assert [call["text"] for call in recovered.calls] == ["0", "1", "2"]


async def test_empty_queue_is_not_an_error(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Пустая очередь — обычное состояние: ни запроса к боту, ни исключения."""
    client = _FakeClient()
    assert await _loop(session_factory, client).run_once() == 0
    assert client.calls == []


async def test_push_without_started_loop_is_a_programming_error(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Отправка без запущенного цикла падает явно, а не тихо ничего не делает."""
    async with session_factory() as session:
        spreadsheet = await create_spreadsheet(session, ready=True)
        assert spreadsheet.id is not None
        await UserNotificationRepository(session).notify(
            spreadsheet.id, NotificationKind.ROLLOVER, "новый период"
        )
        await session.commit()

    with pytest.raises(RuntimeError):
        await _loop(session_factory, None).run_once()


async def test_stop_interrupts_the_sleep_immediately() -> None:
    """Пока цикл спит между проходами, остановка возвращает управление сразу."""
    ticked = asyncio.Event()
    ticks = 0

    async def run_once() -> int:
        nonlocal ticks
        ticks += 1
        ticked.set()
        return 0

    loop = _loop(None)
    loop.run_once = run_once  # type: ignore[method-assign]

    await loop.start()
    await asyncio.wait_for(ticked.wait(), timeout=2)
    await asyncio.wait_for(loop.stop(), timeout=2)

    assert ticks == 1
    assert loop._client is None


async def test_failed_tick_does_not_kill_the_loop() -> None:
    """Ошибка прохода не выносит цикл: иначе система замолчала бы навсегда."""
    failed = asyncio.Event()
    attempts = 0

    async def run_once() -> int:
        nonlocal attempts
        attempts += 1
        failed.set()
        raise RuntimeError("база недоступна")

    loop = _loop(None)
    loop.run_once = run_once  # type: ignore[method-assign]

    await loop.start()
    await asyncio.wait_for(failed.wait(), timeout=2)

    task = loop._task
    assert task is not None
    assert not task.done()

    await asyncio.wait_for(loop.stop(), timeout=2)
    assert attempts == 1
    assert loop._task is None
