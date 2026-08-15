"""Фоновая рассылка накопленных уведомлений в telegram-бота."""

from __future__ import annotations

import asyncio
import contextlib

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.core import constants
from api.core.logging import get_logger
from api.domain.pending_notification import PendingNotification
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository
from api.services.notification_service import NotificationService

logger = get_logger(__name__)


class NotificationLoop:
    """Толкает недоставленные сообщения боту и отмечает подтверждённые.

    Почему push, а не опрос ботом: адресация. Уведомление знает документ, а
    отправлять надо в чат, и эндпоинт чтения устроен «по документу» — бот не
    смог бы узнать, у кого спрашивать, не заведя собственный список
    пользователей, то есть второй источник истины о том, кто вообще есть.

    Почему цикл, а не отправка в момент события: событие рождается в
    транзакции, а отправка — сетевой вызов, который может не удаться. Цикл и
    есть механизм повтора: бот, лежавший в момент правки листа, получит текст
    разбора следующим проходом, а не потеряет его. Ради этого в
    `user_notifications` и живёт `delivered_at`.

    Контракт с ботом: 2xx означает «дальше не повторять» — сообщение отправлено
    либо отправить его невозможно в принципе (пользователь заблокировал бота).
    Всё остальное считается временной неудачей, и сообщение остаётся в очереди.

    Сетевая ошибка прерывает проход целиком: она означает, что бот недоступен, и
    пробовать остальные сообщения незачем — проход растянулся бы на полсотни
    таймаутов подряд.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        notify_url: str,
        interval_seconds: int = constants.NOTIFICATION_PUSH_INTERVAL_SECONDS,
        timeout_seconds: float = constants.NOTIFICATION_PUSH_TIMEOUT_SECONDS,
        limit: int = constants.NOTIFICATION_PUSH_LIMIT,
    ) -> None:
        self._session_factory = session_factory
        self._notify_url = notify_url
        self._interval = interval_seconds
        self._timeout = timeout_seconds
        self._limit = limit
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Запускает цикл, не блокируя вызывающего."""
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._client = httpx.AsyncClient(timeout=self._timeout)
        self._task = asyncio.create_task(self._loop(), name="notification-loop")
        logger.info(
            "Рассылка уведомлений запущена, адрес %s, интервал %s с",
            self._notify_url,
            self._interval,
        )

    async def stop(self) -> None:
        """Просит цикл остановиться и дожидается конца текущего прохода."""
        self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("Рассылка уведомлений остановлена")

    async def _loop(self) -> None:
        """Проход → прерываемый сон → проход."""
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                # Всегда первым: иначе остановка приложения повисла бы на цикле.
                raise
            except Exception:
                # Цикл не должен умирать ни от одной ошибки: он единственный
                # способ сообщить пользователю, что его правки в листе не
                # применились.
                logger.exception("Проход рассылки не удался — продолжаем")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return
            except TimeoutError:
                continue

    async def run_once(self) -> int:
        """Один проход по очереди. Возвращает число доставленных сообщений."""
        async with self._session_factory() as session:
            service = NotificationService(
                session,
                SpreadsheetRepository(session),
                notifications=UserNotificationRepository(session),
            )
            pending = await service.list_pending(limit=self._limit)
            if not pending:
                return 0

            delivered = 0
            for notification in pending:
                try:
                    accepted = await self._push(notification)
                except httpx.RequestError as error:
                    logger.warning(
                        "Бот недоступен (%s) — оставляем %s сообщений в очереди",
                        error,
                        len(pending) - delivered,
                    )
                    break
                if not accepted:
                    continue
                await service.mark_delivered(notification.spreadsheet_id, notification.id)
                delivered += 1

            if delivered:
                logger.info("Доставлено уведомлений: %s", delivered)
            return delivered

    async def _push(self, notification: PendingNotification) -> bool:
        """Отправляет одно сообщение боту. True — повторять не нужно."""
        if self._client is None:
            raise RuntimeError("Клиент рассылки не создан: цикл не запущен")

        response = await self._client.post(
            self._notify_url,
            json={
                "notification_id": notification.id,
                "telegram_id": notification.telegram_id,
                "kind": notification.kind.value,
                "text": notification.text,
            },
        )
        if response.is_success:
            return True
        logger.warning(
            "Бот отклонил уведомление %s: %s %s",
            notification.id,
            response.status_code,
            response.text[:200],
        )
        return False
