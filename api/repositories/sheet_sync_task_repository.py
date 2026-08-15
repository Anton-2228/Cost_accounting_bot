"""Репозиторий очереди перерисовки листов."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.domain.sheet_sync_task import SheetSyncTask
from api.enums import SheetTarget, SyncTaskKind
from api.mappers.sheet_sync_task_mapper import SheetSyncTaskMapper
from api.orm.sheet_sync_task import SheetSyncTaskORM
from api.repositories.base import BaseRepository, affected_rows

#: Ключ задачи: документ, направление, адресат, период.
type TaskKey = tuple[int, SyncTaskKind, SheetTarget, int | None]


class SheetSyncTaskRepository(BaseRepository[SheetSyncTaskORM, SheetSyncTask]):
    """Очередь исходящих изменений: какие листы устарели и подлежат перерисовке.

    Задача описывает не изменение, а устаревание, поэтому повтор безопасен,
    порядок обработки не важен, а сама перерисовка строится из текущего
    состояния БД целиком.
    """

    orm_type = SheetSyncTaskORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SheetSyncTaskMapper())

    async def enqueue(
        self,
        spreadsheet_id: int,
        target: SheetTarget,
        period_id: int | None = None,
        *,
        kind: SyncTaskKind = SyncTaskKind.REDRAW,
    ) -> None:
        """Отмечает лист устаревшим. Вызывается в одной транзакции с изменением данных.

        Повторный вызов не создаёт вторую строку, а двигает `requested_at`
        вперёд: десять быстрых операций подряд оставляют одну задачу, и лист
        перерисовывается один раз вместо десяти.
        """
        await self.enqueue_many([(spreadsheet_id, kind, target, period_id)])

    async def enqueue_many(self, keys: Iterable[TaskKey]) -> None:
        """Отмечает устаревшими сразу несколько листов одним оператором."""
        # Дедупликация обязательна: PostgreSQL падает с «ON CONFLICT DO UPDATE
        # command cannot affect row a second time», если в одном INSERT
        # встречаются два одинаковых ключа.
        unique_keys = list(dict.fromkeys(keys))
        if not unique_keys:
            return

        stmt = pg_insert(SheetSyncTaskORM).values(
            [
                {
                    "spreadsheet_id": spreadsheet_id,
                    "kind": kind,
                    "target": target,
                    "period_id": period_id,
                }
                for spreadsheet_id, kind, target, period_id in unique_keys
            ]
        )
        await self._session.execute(
            stmt.on_conflict_do_update(
                constraint="uq_sheet_sync_tasks_key",
                set_={
                    "requested_at": func.now(),
                    # Ссылка именно на колонку таблицы, а не на stmt.excluded:
                    # в excluded лежит серверный default now() вставляемой
                    # строки, и LEAST выродился бы в now(). Задача, отложенная
                    # после ошибки, начала бы выбираться немедленно, и backoff
                    # перестал бы работать.
                    "next_attempt_at": func.least(
                        SheetSyncTaskORM.next_attempt_at,
                        func.now(),
                    ),
                },
            )
        )
        await self._session.flush()

    async def claim(self, limit: int = constants.SHEET_SYNC_CLAIM_LIMIT) -> list[SheetSyncTask]:
        """Забирает пачку задач, у которых подошёл срок.

        `FOR UPDATE SKIP LOCKED` позволяет нескольким воркерам разбирать очередь
        одновременно, не дожидаясь друг друга.

        Захват имеет срок (:data:`api.core.constants.SHEET_SYNC_LEASE_SECONDS`),
        и просроченный не мешает выборке. Снимают захват `complete`, `release` и
        `fail`, но воркер может не дожить ни до одного из них: между `claim` и
        отчётом его способны убить рестарт, OOM или потеря сети. Без срока такая
        задача осталась бы забранной навсегда, и лист замер бы **молча** —
        уведомление о неудаче шлёт `fail`, которого в этом сценарии не будет.

        Подзапрос отбора остаётся простым `SELECT id`: `FOR UPDATE` несовместим
        с агрегатами, `GROUP BY` и `DISTINCT`.

        Вызывающий должен зафиксировать транзакцию сразу после `claim` —
        блокировки живут до её конца, и долгая перерисовка листа держала бы
        очередь запертой для остальных.
        """
        lease_deadline = func.now() - timedelta(seconds=constants.SHEET_SYNC_LEASE_SECONDS)
        picked = (
            select(SheetSyncTaskORM.id)
            .where(
                or_(
                    SheetSyncTaskORM.claimed_at.is_(None),
                    SheetSyncTaskORM.claimed_at < lease_deadline,
                ),
                SheetSyncTaskORM.next_attempt_at <= func.now(),
            )
            .order_by(SheetSyncTaskORM.requested_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(SheetSyncTaskORM)
            .where(SheetSyncTaskORM.id.in_(picked))
            .values(claimed_at=func.now())
            .returning(SheetSyncTaskORM)
        )
        rows = (await self._session.scalars(stmt)).all()
        return self._mapper.to_domain_list(rows)

    async def complete(self, task_id: int, requested_at: datetime) -> bool:
        """Удаляет выполненную задачу, если за время работы её не запросили заново.

        Условие по `requested_at` — сердце всей схемы. Пока воркер перерисовывал
        лист, пользователь мог сделать ещё одну операцию; она подняла бы
        `requested_at` на уже забранной строке. Безусловное удаление потеряло бы
        это изменение до следующей правки.

        Возвращает False, если задача осталась: значит, лист снова устарел и его
        нужно перерисовать ещё раз (см. :meth:`release`).
        """
        result = await self._session.execute(
            delete(SheetSyncTaskORM).where(
                SheetSyncTaskORM.id == task_id,
                SheetSyncTaskORM.requested_at == requested_at,
            )
        )
        await self._session.flush()
        return bool(affected_rows(result))

    async def release(self, task_id: int) -> None:
        """Снимает захват, не трогая счётчик попыток.

        Нужен после :meth:`complete`, вернувшего False: работа выполнена
        успешно, но появилось новое изменение, поэтому задача должна снова стать
        доступной для выборки.
        """
        await self._session.execute(
            update(SheetSyncTaskORM)
            .where(SheetSyncTaskORM.id == task_id)
            .values(claimed_at=None, next_attempt_at=func.now())
        )
        await self._session.flush()

    async def fail(
        self,
        task_id: int,
        error: str,
        *,
        terminal: bool = False,
    ) -> SheetSyncTask | None:
        """Возвращает задачу в очередь с увеличенным счётчиком попыток и паузой.

        Пауза растёт экспоненциально и ограничена сверху: недоступность Google
        не должна превращаться в поток повторов, но и не должна откладывать
        перерисовку на сутки.

        `terminal` означает, что повтор заведомо получит тот же ответ: файл
        удалён, доступ отозван, лист не найден. Такой задаче сразу ставится
        длинная пауза вместо экспоненты — начинать с пяти секунд бессмысленно,
        пока не вмешается пользователь. Из очереди задача при этом **не
        исчезает**: доступ могут вернуть, и тогда лист обязан догнать сам.

        Возвращает обновлённую задачу (или `None`, если её уже нет), чтобы
        вызывающему не пришлось читать её второй раз ради счётчика попыток.
        """
        task = await self._session.get(SheetSyncTaskORM, task_id)
        if task is None:
            return None

        attempts = task.attempts + 1
        if terminal:
            delay = constants.SHEET_SYNC_TERMINAL_RETRY_SECONDS
        else:
            delay = min(
                constants.SHEET_SYNC_RETRY_BASE_SECONDS * 2 ** (attempts - 1),
                constants.SHEET_SYNC_RETRY_MAX_SECONDS,
            )
        orm = (
            await self._session.scalars(
                update(SheetSyncTaskORM)
                .where(SheetSyncTaskORM.id == task_id)
                .values(
                    claimed_at=None,
                    attempts=attempts,
                    next_attempt_at=func.now() + timedelta(seconds=delay),
                    last_error=error[: constants.NOTES_MAX_LENGTH],
                )
                .returning(SheetSyncTaskORM)
            )
        ).one_or_none()
        await self._session.flush()
        return None if orm is None else self._mapper.to_domain(orm)

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> Sequence[SheetSyncTask]:
        """Возвращает задачи документа. Нужно для диагностики и тестов."""
        rows = (
            await self._session.scalars(
                select(SheetSyncTaskORM)
                .where(SheetSyncTaskORM.spreadsheet_id == spreadsheet_id)
                .order_by(SheetSyncTaskORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)
