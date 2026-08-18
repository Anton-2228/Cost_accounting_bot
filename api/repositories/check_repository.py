"""Репозиторий сохранённых чеков."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.domain.check import Check
from api.enums import CheckKind
from api.mappers.check_mapper import CheckMapper
from api.orm.check import CheckORM
from api.orm.record import RecordORM
from api.repositories.base import BaseRepository


class CheckRepository(BaseRepository[CheckORM, Check]):
    """Доступ к сохранённым чекам документа."""

    orm_type = CheckORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, CheckMapper())

    async def get_by_external_key(
        self,
        spreadsheet_id: int,
        kind: CheckKind,
        external_key: str,
    ) -> Check | None:
        """Находит уже сохранённый **живой** чек по ключу формата.

        Ключ вычисляет парсер (для ФНС — «ФН:ФД:ФП»), поэтому вид входит в
        условие: один и тот же набор цифр в двух форматах — разные чеки.

        Удалённые не ищутся, и это то же правило, что стоит в БД частичным
        уникальным индексом: ту же бумажку после удаления разрешено
        отсканировать заново, поэтому «уже добавлен» про неё говорить нельзя.
        """
        orm = (
            await self._session.scalars(
                select(CheckORM).where(
                    CheckORM.spreadsheet_id == spreadsheet_id,
                    CheckORM.kind == kind,
                    CheckORM.external_key == external_key,
                    CheckORM.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def get_for_spreadsheet(self, check_id: int, spreadsheet_id: int) -> Check | None:
        """Возвращает живой чек, только если он принадлежит указанному документу.

        Проверка принадлежности здесь, а не в сервисе после чтения по id:
        иначе разбор чужого чека отличался бы от разбора несуществующего только
        порядком строк в сервисе.

        Удалённый чек не находится: без этого условия `commit_check` записал бы
        операции в чек, которого в документе больше нет.
        """
        orm = (
            await self._session.scalars(
                select(CheckORM).where(
                    CheckORM.id == check_id,
                    CheckORM.spreadsheet_id == spreadsheet_id,
                    CheckORM.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def list_by_spreadsheet(
        self,
        spreadsheet_id: int,
        *,
        unprocessed: bool = False,
    ) -> list[Check]:
        """Возвращает живые чеки документа в порядке поступления.

        `unprocessed=True` оставляет только ждущие разбора — это и есть очередь
        бота, поэтому порядок «от самого старого» существен: чек, пролежавший
        неделю, должен быть разобран раньше сегодняшнего.
        """
        stmt = select(CheckORM).where(
            CheckORM.spreadsheet_id == spreadsheet_id,
            CheckORM.deleted_at.is_(None),
        )
        if unprocessed:
            stmt = stmt.where(CheckORM.processed_at.is_(None))
        rows = (await self._session.scalars(stmt.order_by(CheckORM.id))).all()
        return self._mapper.to_domain_list(rows)

    async def list_processed_for_period(
        self,
        spreadsheet_id: int,
        period_id: int,
    ) -> list[Check]:
        """Чеки, чьи операции попали в указанный период.

        Своего периода у чека нет: он приходит из Mini App, когда учётный месяц
        его ещё не касается, а месяц ему назначает разбор. Поэтому
        принадлежность выводится из операций — единственного, что связывает чек
        с реестром.

        Мягко удалённые операции **учитываются**: пользователь, удаливший одну
        строку реестра, не отзывал чек, и архив не должен терять его из-за
        правки одной позиции. Из архива чек выносит только собственная метка
        `deleted_at` — а её ставит удаление последней его живой операции.
        Месяц у чека поэтому не меняется: он выведен из операций, живых и
        удалённых вместе.
        """
        stmt = (
            select(CheckORM)
            .where(
                CheckORM.spreadsheet_id == spreadsheet_id,
                CheckORM.deleted_at.is_(None),
                CheckORM.id.in_(
                    select(RecordORM.check_id).where(
                        RecordORM.spreadsheet_id == spreadsheet_id,
                        RecordORM.period_id == period_id,
                        RecordORM.check_id.is_not(None),
                    )
                ),
            )
            .order_by(CheckORM.id)
        )
        rows = (await self._session.scalars(stmt)).all()
        return self._mapper.to_domain_list(rows)

    async def mark_processed(self, check_id: int, *, at: datetime) -> Check | None:
        """Отмечает живой чек разобранным; `None`, если отмечать нечего.

        Условие `processed_at IS NULL` обязательно: без него повтор переписал бы
        метку и сообщил бы об успехе там, где ничего не изменилось. Условие
        `deleted_at IS NULL` — по той же причине: разбор не должен отмечать чек,
        удалённый между проверкой в сервисе и этим оператором.

        Результат возвращается через `RETURNING`, а не перечитыванием: при
        `expire_on_commit=False` объект в сессии после `UPDATE` остаётся
        прежним, и повторное чтение отдало бы старое значение.
        """
        orm = (
            await self._session.scalars(
                update(CheckORM)
                .where(
                    CheckORM.id == check_id,
                    CheckORM.processed_at.is_(None),
                    CheckORM.deleted_at.is_(None),
                )
                .values(processed_at=at)
                .returning(CheckORM)
            )
        ).one_or_none()
        await self._session.flush()
        return None if orm is None else self._mapper.to_domain(orm)
