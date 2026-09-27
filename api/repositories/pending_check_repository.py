"""Репозиторий отложенных чеков."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.domain.pending_check import PendingCheck
from api.enums import CheckKind
from api.mappers.pending_check_mapper import PendingCheckMapper
from api.orm.pending_check import PendingCheckORM
from api.repositories.base import BaseRepository, affected_rows


def retry_delay(attempts: int) -> timedelta:
    """Пауза перед следующей попыткой после `attempts` уже сделанных.

    Первая попытка — сам скан, поэтому первый повтор идёт через базовую паузу,
    а дальше пауза удваивается до потолка: 15 мин, 30 мин, 1 ч, 2 ч, … 6 ч.
    """
    seconds = constants.PENDING_CHECK_RETRY_BASE_SECONDS * 2 ** max(attempts - 1, 0)
    return timedelta(seconds=min(seconds, constants.PENDING_CHECK_RETRY_MAX_SECONDS))


class PendingCheckRepository(BaseRepository[PendingCheckORM, PendingCheck]):
    """Доступ к отложенным чекам и их очереди повторов."""

    orm_type = PendingCheckORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PendingCheckMapper())

    async def now(self) -> datetime:
        """Время по часам БД.

        Окно попыток и срок аренды считаются от `now()` в SQL, и сравнивать с
        ними время по часам процесса значило бы смешать двое часов.
        """
        value = await self._session.scalar(select(func.now()))
        assert value is not None
        return value

    async def get_for_spreadsheet(
        self,
        pending_id: int,
        spreadsheet_id: int,
    ) -> PendingCheck | None:
        """Отложенный чек, только если он принадлежит указанному документу."""
        orm = (
            await self._session.scalars(
                select(PendingCheckORM).where(
                    PendingCheckORM.id == pending_id,
                    PendingCheckORM.spreadsheet_id == spreadsheet_id,
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def list_by_spreadsheet(self, spreadsheet_id: int) -> list[PendingCheck]:
        """Отложенные чеки документа в порядке сканирования."""
        rows = (
            await self._session.scalars(
                select(PendingCheckORM)
                .where(PendingCheckORM.spreadsheet_id == spreadsheet_id)
                .order_by(PendingCheckORM.id)
            )
        ).all()
        return self._mapper.to_domain_list(rows)

    async def add_or_get(
        self,
        spreadsheet_id: int,
        *,
        kind: CheckKind,
        qr_raw: str,
        external_key: str,
        error: str,
    ) -> PendingCheck:
        """Откладывает чек; уже отложенный возвращает как есть.

        `ON CONFLICT DO NOTHING`, а не проверка и вставка: между ними
        помещается второй скан того же чека (двойное нажатие, два телефона),
        и без этого гонка отвечала бы пятисоткой. Окно и счётчик попыток у
        существующей строки не трогаются — повторный скан не продлевает ожидание.
        """
        stmt = (
            pg_insert(PendingCheckORM)
            .values(
                spreadsheet_id=spreadsheet_id,
                kind=kind,
                qr_raw=qr_raw,
                external_key=external_key,
                attempts=1,
                next_attempt_at=func.now() + retry_delay(1),
                last_error=error,
            )
            .on_conflict_do_nothing(
                constraint="uq_pending_checks_spreadsheet_id_kind_external_key",
            )
            .returning(PendingCheckORM)
        )
        orm = (await self._session.scalars(stmt)).one_or_none()
        if orm is None:
            orm = (
                await self._session.scalars(
                    select(PendingCheckORM).where(
                        PendingCheckORM.spreadsheet_id == spreadsheet_id,
                        PendingCheckORM.kind == kind,
                        PendingCheckORM.external_key == external_key,
                    )
                )
            ).one()
        await self._session.flush()
        return self._mapper.to_domain(orm)

    async def delete_by_key(
        self,
        spreadsheet_id: int,
        kind: CheckKind,
        external_key: str,
    ) -> int:
        """Убирает отложенный чек по ключу формата; возвращает число удалённых.

        Зовётся при сохранении чека: как бы он ни дошёл — фоном, ручным
        повтором или новым сканом, — ждать его больше незачем.
        """
        result = await self._session.execute(
            delete(PendingCheckORM).where(
                PendingCheckORM.spreadsheet_id == spreadsheet_id,
                PendingCheckORM.kind == kind,
                PendingCheckORM.external_key == external_key,
            )
        )
        await self._session.flush()
        return affected_rows(result)

    async def claim_due(
        self,
        limit: int = constants.PENDING_CHECK_CLAIM_LIMIT,
    ) -> list[PendingCheck]:
        """Забирает неистёкшие чеки, у которых подошёл срок повтора.

        Устроено как `SheetSyncTaskRepository.claim`: `FOR UPDATE SKIP LOCKED`
        и аренда со сроком. Вызывающий обязан зафиксировать транзакцию сразу.
        """
        picked = (
            select(PendingCheckORM.id)
            .where(
                PendingCheckORM.expired_at.is_(None),
                PendingCheckORM.next_attempt_at <= func.now(),
                self._lease_free(),
            )
            .order_by(PendingCheckORM.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(PendingCheckORM)
            .where(PendingCheckORM.id.in_(picked))
            .values(claimed_at=func.now())
            .returning(PendingCheckORM)
        )
        rows = (await self._session.scalars(stmt)).all()
        return self._mapper.to_domain_list(rows)

    async def claim_one(self, pending_id: int, spreadsheet_id: int) -> PendingCheck | None:
        """Забирает конкретный чек для ручного повтора; `None`, если он занят.

        Срок повтора и истечение окна здесь не важны: пользователь нажал
        «Повторить» — значит, спрашиваем сейчас. Важна только аренда, иначе
        ручной повтор и фон пошли бы во внешний сервис одновременно.
        """
        orm = (
            await self._session.scalars(
                update(PendingCheckORM)
                .where(
                    PendingCheckORM.id == pending_id,
                    PendingCheckORM.spreadsheet_id == spreadsheet_id,
                    self._lease_free(),
                )
                .values(claimed_at=func.now())
                .returning(PendingCheckORM)
            )
        ).one_or_none()
        await self._session.flush()
        return None if orm is None else self._mapper.to_domain(orm)

    async def record_failure(
        self,
        pending_id: int,
        error: str,
        *,
        manual: bool,
    ) -> PendingCheck | None:
        """Отмечает неудачную попытку и назначает следующую.

        Ручной повтор открывает окно заново: пользователь сам вернул чек в
        работу, и считать его истёкшим после первой же неудачи было бы
        странно. Фоновая неудача после конца окна истекает чек — дальше фон его
        не трогает.

        Возвращает обновлённую строку или `None`, если её уже нет (чек успели
        сохранить или удалить, пока шла попытка).
        """
        orm = await self._session.get(PendingCheckORM, pending_id, with_for_update=True)
        if orm is None:
            return None

        now = await self.now()
        window = timedelta(seconds=constants.PENDING_CHECK_WINDOW_SECONDS)
        values: dict[str, object] = {"claimed_at": None, "last_error": error}
        if manual:
            values.update(
                attempts=1,
                window_started_at=now,
                next_attempt_at=now + retry_delay(1),
                expired_at=None,
            )
        else:
            attempts = orm.attempts + 1
            values["attempts"] = attempts
            if orm.expired_at is None and now - orm.window_started_at >= window:
                values["expired_at"] = now
            values["next_attempt_at"] = now + retry_delay(attempts)

        updated = (
            await self._session.scalars(
                update(PendingCheckORM)
                .where(PendingCheckORM.id == pending_id)
                .values(**values)
                .returning(PendingCheckORM)
            )
        ).one()
        await self._session.flush()
        return self._mapper.to_domain(updated)

    @staticmethod
    def _lease_free() -> ColumnElement[bool]:
        """Условие «чек не захвачен или захват просрочен»."""
        deadline = func.now() - timedelta(seconds=constants.PENDING_CHECK_LEASE_SECONDS)
        return or_(PendingCheckORM.claimed_at.is_(None), PendingCheckORM.claimed_at < deadline)
