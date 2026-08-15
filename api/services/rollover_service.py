"""Смена учётного месяца: создание новых периодов и закрытие закончившихся."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants, messages
from api.core.logging import get_logger
from api.core.period import catch_up_starts, now_in_timezone, period_bounds, period_end
from api.db.transaction import commit
from api.domain.period import Period
from api.domain.spreadsheet import Spreadsheet
from api.enums import NotificationKind, SheetTarget, SyncTaskKind
from api.repositories.period_repository import PeriodRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.repositories.user_notification_repository import UserNotificationRepository

logger = get_logger(__name__)


class RolloverService:
    """Догоняющая смена периода по всем документам.

    Ролловер идемпотентен целиком: период создаётся через `ensure` (уникальный
    ключ `(spreadsheet_id, start_date)`), закрытие проверяет текущий статус,
    задачи очереди схлопываются по своему ключу. Поэтому лишний проход ничего не
    портит, а пропущенный — навёрстывается следующим.

    Прежний ролловер сдвигал указатель `start_date` прямо в документе и
    срабатывал только при точном равенстве `today == end_date`: простой сервиса
    в день сброса означал безвозвратно пропущенный месяц, а сбой на создании
    листа оставлял документ сломанным навсегда — указатель уже уехал, а листа
    нет.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        periods: PeriodRepository,
        tasks: SheetSyncTaskRepository,
        notifications: UserNotificationRepository,
    ) -> None:
        self._session = session
        self._spreadsheets = spreadsheets
        self._periods = periods
        self._tasks = tasks
        self._notifications = notifications

    async def run_once(self) -> int:
        """Проходит по всем документам. Возвращает число изменённых.

        Каждый документ — своя транзакция: один сломанный документ не должен
        мешать остальным сменить месяц. Ошибку логируем и идём дальше, иначе
        ролловер встал бы навсегда, повторяя одно и то же падение каждый проход.
        """
        changed = 0
        for spreadsheet in await self._spreadsheets.list_all():
            if spreadsheet.id is None:
                continue
            try:
                if await self.rollover(spreadsheet):
                    changed += 1
            except Exception:
                logger.exception("Ролловер документа %s не удался", spreadsheet.id)
                await self._session.rollback()
        return changed

    async def rollover(self, spreadsheet: Spreadsheet) -> bool:
        """Догоняет периоды одного документа и закрывает закончившиеся.

        Возвращает True, если что-то изменилось.
        """
        assert spreadsheet.id is not None
        if not await self._try_lock(spreadsheet.id):
            # Этот документ уже обрабатывает другой воркер. Возвращаться к нему
            # незачем: он идемпотентен, и следующий проход всё равно проверит
            # его заново.
            logger.debug("Документ %s уже обрабатывается, пропуск", spreadsheet.id)
            return False

        now = now_in_timezone(spreadsheet.timezone)
        today = now.date()

        created = await self._ensure_periods(spreadsheet, today)
        closed = await self._close_finished(spreadsheet.id, today, now)
        if not created and not closed:
            await self._session.rollback()
            return False

        keys: list[TaskKey] = []
        if created:
            # Листы нового периода создаёт `google_sheets_service` по задаче
            # STRUCTURE; перерисовка без них не найдёт, куда писать.
            keys.append((spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.STRUCTURE, None))
            for period in created:
                keys += [
                    (spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period.id),
                    (spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.STATISTICS, period.id),
                ]
            await self._notifications.notify(
                spreadsheet.id,
                NotificationKind.ROLLOVER,
                messages.rollover_done(created[-1].start_date),
            )
        if closed:
            # Итоги закрытого месяца рисуются последний раз: пользователь мог
            # добавить операцию в последние минуты периода.
            for period_id in closed:
                keys += [
                    (spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period_id),
                    (spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.STATISTICS, period_id),
                ]
        keys.append((spreadsheet.id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None))

        await self._tasks.enqueue_many(keys)
        await commit(self._session)
        logger.info(
            "Ролловер документа %s: создано периодов %s, закрыто %s",
            spreadsheet.id,
            len(created),
            len(closed),
        )
        return True

    async def _try_lock(self, spreadsheet_id: int) -> bool:
        """Берёт рекомендательную блокировку документа на текущую транзакцию.

        Блокировка транзакционная (`pg_try_advisory_xact_lock`), а не сессионная:
        она снимается вместе с транзакцией, поэтому не может остаться висеть,
        если процесс умер посреди прохода. Парная форма — «пространство имён,
        объект», как это принято для advisory-блокировок в Postgres.
        """
        locked = await self._session.scalar(
            select(
                func.pg_try_advisory_xact_lock(
                    constants.ROLLOVER_ADVISORY_LOCK_NAMESPACE,
                    spreadsheet_id,
                )
            )
        )
        return bool(locked)

    async def _ensure_periods(self, spreadsheet: Spreadsheet, today: date) -> list[Period]:
        """Создаёт все периоды, которых не хватает, вплоть до сегодняшнего.

        Первый период документа создаётся вместе с ним, но проверка на его
        отсутствие всё равно нужна: документ мог быть создан в обход сервиса
        (перенос данных, ручная правка), и без периода он был бы неработоспособен.
        """
        assert spreadsheet.id is not None
        latest = await self._periods.get_latest(spreadsheet.id)
        if latest is None:
            start_date, end_date = period_bounds(today, spreadsheet.reset_day)
            return [await self._periods.ensure(spreadsheet.id, start_date, end_date)]

        created: list[Period] = []
        for start_date in catch_up_starts(latest.start_date, today):
            created.append(
                await self._periods.ensure(spreadsheet.id, start_date, period_end(start_date))
            )
        return created

    async def _close_finished(
        self,
        spreadsheet_id: int,
        today: date,
        now: datetime,
    ) -> list[int]:
        """Закрывает все открытые периоды, которые уже закончились.

        Закрытый период не меняется: и добавление, и удаление задним числом
        поменяли бы итоги, которые пользователь уже видел. Заодно это ограничивает
        веер задач перерисовки — иначе любая правка справочника перерисовывала бы
        все месяцы за всю историю документа.
        """
        closed: list[int] = []
        for period in await self._periods.list_open(spreadsheet_id):
            if period.id is None or period.end_date > today:
                continue
            if await self._periods.close(period.id, at=now):
                closed.append(period.id)
        return closed
