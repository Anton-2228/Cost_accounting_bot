"""Репозиторий источников денег, включая агрегат баланса."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, Row, case, delete, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.core import constants
from api.core.text import normalize_terms
from api.db.column_types import MONEY
from api.domain.exchange_rate import RateRequirement
from api.domain.source import Source
from api.domain.source_balance import SourceBalance
from api.enums import EntityStatus
from api.mappers.source_mapper import SourceMapper
from api.orm.record import RecordORM
from api.orm.source import SourceORM
from api.orm.source_association import SourceAssociationORM
from api.orm.transfer import TransferORM
from api.rates.base import RateUnavailableError
from api.repositories._rates import rate_factor
from api.repositories.base import BaseRepository

# Ноль нужного типа. Без явного Numeric COALESCE с целочисленным литералом
# может вернуть не Decimal, и денежная арифметика поедет по типам.
_ZERO = literal(Decimal("0"), MONEY)


class SourceRepository(BaseRepository[SourceORM, Source]):
    """Доступ к счетам и расчёт их текущего баланса."""

    orm_type = SourceORM

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SourceMapper())

    async def list_by_spreadsheet(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
        include_deleted: bool = False,
    ) -> list[Source]:
        """Возвращает счета документа, отсортированные по id."""
        stmt = select(SourceORM).where(SourceORM.spreadsheet_id == spreadsheet_id)
        if not include_deleted:
            stmt = stmt.where(SourceORM.deleted_at.is_(None))
        if only_active:
            stmt = stmt.where(SourceORM.status == EntityStatus.ACTIVE)
        rows = (await self._session.scalars(stmt.order_by(SourceORM.id))).all()
        return self._mapper.to_domain_list(rows)

    async def get_for_spreadsheet(
        self,
        source_id: int,
        spreadsheet_id: int,
        *,
        include_deleted: bool = False,
    ) -> Source | None:
        """Возвращает счёт, только если он принадлежит указанному документу."""
        stmt = select(SourceORM).where(
            SourceORM.id == source_id,
            SourceORM.spreadsheet_id == spreadsheet_id,
        )
        if not include_deleted:
            stmt = stmt.where(SourceORM.deleted_at.is_(None))
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def find_by_association(self, spreadsheet_id: int, alias: str) -> Source | None:
        """Находит живой счёт по псевдониму.

        Однозначность обеспечивает уникальный ключ дочерней таблицы, а не
        порядок перебора: прежняя реализация просматривала все счета и
        оставляла последнее совпадение, поэтому при дублирующемся псевдониме
        результат зависел от порядка строк.
        """
        stmt = (
            select(SourceORM)
            .join(SourceAssociationORM, SourceAssociationORM.source_id == SourceORM.id)
            .where(
                SourceORM.spreadsheet_id == spreadsheet_id,
                SourceAssociationORM.alias == alias.strip().lower(),
                SourceORM.deleted_at.is_(None),
            )
        )
        orm = (await self._session.scalars(stmt)).one_or_none()
        return None if orm is None else self._mapper.to_domain(orm)

    async def replace_associations_bulk(
        self,
        by_source: Mapping[int, Iterable[str]],
    ) -> None:
        """Заменяет псевдонимы сразу у нескольких счетов одного документа.

        Уникальность псевдонима действует на весь документ, поэтому обмен
        псевдонимами между двумя счетами нельзя выполнить по одному: вставка
        первого упрётся в псевдоним, который второй ещё не отдал. Работает
        только общее удаление → `flush` → общая вставка.
        """
        if not by_source:
            return

        rows = (
            await self._session.scalars(select(SourceORM).where(SourceORM.id.in_(by_source)))
        ).all()
        spreadsheet_by_source = {orm.id: orm.spreadsheet_id for orm in rows}

        await self._session.execute(
            delete(SourceAssociationORM).where(SourceAssociationORM.source_id.in_(by_source))
        )
        await self._session.flush()

        self._session.add_all(
            [
                SourceAssociationORM(
                    spreadsheet_id=spreadsheet_by_source[source_id],
                    source_id=source_id,
                    alias=alias,
                )
                for source_id, aliases in by_source.items()
                if source_id in spreadsheet_by_source
                for alias in normalize_terms(aliases)
            ]
        )
        await self._session.flush()

    async def replace_associations(self, source_id: int, aliases: Iterable[str]) -> Source | None:
        """Заменяет набор псевдонимов счёта: удаляет все и вставляет заданные.

        `flush` между удалением и вставкой обязателен. Без него SQLAlchemy
        выдаёт `INSERT` раньше `DELETE` в пределах одного flush, и добавление
        псевдонима к существующему набору падает на уникальном ключе — старая
        строка с тем же значением ещё жива.
        """
        orm = await self._session.get(SourceORM, source_id)
        if orm is None:
            return None

        await self._session.execute(
            delete(SourceAssociationORM).where(SourceAssociationORM.source_id == source_id)
        )
        await self._session.flush()

        self._session.add_all(
            [
                SourceAssociationORM(
                    spreadsheet_id=orm.spreadsheet_id,
                    source_id=source_id,
                    alias=alias,
                )
                for alias in normalize_terms(aliases)
            ]
        )
        await self._session.flush()
        await self._session.refresh(orm)
        return self._mapper.to_domain(orm)

    async def balances(
        self,
        spreadsheet_id: int,
        *,
        only_active: bool = False,
    ) -> list[SourceBalance]:
        """Считает текущие балансы живых счетов документа одним запросом.

        Баланс не хранится: он равен начальному балансу плюс операции, плюс
        входящие переводы, минус исходящие. Поэтому расхождение баланса с
        реестром — не редкое состояние, которое надо ловить, а невыразимое.

        Считается **тремя коррелированными подзапросами**, а не тремя `LEFT JOIN`
        с `GROUP BY`. Соединение перемножило бы строки: три операции, два
        входящих перевода и два исходящих дали бы двенадцать строк, и каждая
        сумма посчиталась бы кратно числу строк остальных таблиц.

        Результат выражен в валюте счёта: операция и перевод в другой валюте
        приводятся к ней по курсу на свой день. Курсы обязаны лежать в кэше к
        моменту вызова — их догружает
        :meth:`api.services.exchange_rate_service.ExchangeRateService.ensure`
        по списку из :meth:`balance_requirements`. Вызвать этот метод, минуя
        `ensure`, значит получить отказ, а не тихо занижённый остаток — см.
        :meth:`_to_balance`.
        """
        stmt = select(
            SourceORM.id,
            SourceORM.title,
            SourceORM.start_balance,
            self._balance_expression().label("balance"),
        ).where(
            SourceORM.spreadsheet_id == spreadsheet_id,
            SourceORM.deleted_at.is_(None),
        )
        if only_active:
            stmt = stmt.where(SourceORM.status == EntityStatus.ACTIVE)

        rows = (await self._session.execute(stmt.order_by(SourceORM.id))).all()
        return [self._to_balance(row) for row in rows]

    async def balance_of(self, source_id: int) -> SourceBalance | None:
        """Считает баланс одного счёта."""
        stmt = select(
            SourceORM.id,
            SourceORM.title,
            SourceORM.start_balance,
            self._balance_expression().label("balance"),
        ).where(SourceORM.id == source_id)

        row = (await self._session.execute(stmt)).one_or_none()
        return None if row is None else self._to_balance(row)

    @staticmethod
    def _to_balance(row: Row[Any]) -> SourceBalance:
        """Строка результата → :class:`SourceBalance`; `NULL` в сумме — отказ.

        `NULL` здесь означает ровно одно: какой-то операции не хватило курса, и
        запрос честно отказался складывать то, что сложить нельзя (см.
        :meth:`_total`). Единственный законный способ это получить — позвать
        подсчёт, не загрузив курсы, то есть в обход
        :meth:`api.services.exchange_rate_service.ExchangeRateService.ensure`.

        Ошибка та же, что и при недоступном источнике курсов, и это не натяжка:
        снаружи оба случая — «курса нет», оба лечатся повтором, и в обоих лучше
        показать прежние верные числа, чем свежие неверные.
        """
        if row.balance is None:
            raise RateUnavailableError(
                "Не хватает курса, чтобы посчитать остаток счёта",
                details={"source_id": row.id},
            )
        return SourceBalance(
            source_id=row.id,
            title=row.title,
            start_balance=row.start_balance,
            balance=row.balance,
        )

    async def balance_requirements(self, spreadsheet_id: int) -> set[RateRequirement]:
        """Какие курсы нужны, чтобы посчитать балансы этого документа.

        Ходит по тем же таблицам и с теми же условиями, что и сам агрегат, — и
        это не стилистическое совпадение, а требование. Курса, которого нет в
        кэше, подзапрос в :meth:`_rate_factor` не найдёт, умножение даст `NULL`,
        а `SUM` молча выбросит слагаемое: остаток занизится ровно на эту
        операцию и ничем себя не выдаст. Разъедься два запроса — и ошибка
        станет невидимой.

        Мягко удалённые **счета** здесь намеренно не отфильтрованы, хотя
        :meth:`balances` их не показывает. Лишний курс стоит одной строки в
        кэше, недостающий — молчаливо неверного числа; при такой цене ошибки
        перестраховка идёт в сторону лишнего.
        """
        records = (
            select(RecordORM.currency, SourceORM.currency, RecordORM.added_at)
            .join(SourceORM, SourceORM.id == RecordORM.source_id)
            .where(
                SourceORM.spreadsheet_id == spreadsheet_id,
                RecordORM.deleted_at.is_(None),
                RecordORM.currency != SourceORM.currency,
            )
            .distinct()
        )

        from_source = aliased(SourceORM, name="from_source")
        to_source = aliased(SourceORM, name="to_source")
        transfers = (
            select(from_source.currency, to_source.currency, TransferORM.added_at)
            .join(from_source, from_source.id == TransferORM.from_source_id)
            .join(to_source, to_source.id == TransferORM.to_source_id)
            .where(
                to_source.spreadsheet_id == spreadsheet_id,
                TransferORM.deleted_at.is_(None),
                from_source.currency != to_source.currency,
            )
            .distinct()
        )

        rows = (await self._session.execute(records.union(transfers))).all()
        return {(row[0], row[1], row[2]) for row in rows}

    # --- Составные части агрегата баланса ---

    @classmethod
    def _balance_expression(cls) -> ColumnElement[Decimal]:
        """Начальный баланс + операции + входящие переводы − исходящие.

        Всё приведено к валюте счёта по курсу на день каждой операции.
        Округление одно, в самом конце: промежуточные произведения несут
        двенадцать знаков курса, и округлять их по дороге значило бы копить
        ошибку на каждой операции вместо одной на весь остаток.
        """
        total = (
            SourceORM.start_balance
            + cls._records_sum()
            + cls._incoming_transfers_sum()
            - cls._outgoing_transfers_sum()
        )
        return func.round(total, constants.MONEY_DECIMAL_PLACES)

    @staticmethod
    def _total(amount: ColumnElement[Decimal]) -> ColumnElement[Decimal]:
        """Сумма слагаемых — либо `NULL`, если хоть одно посчитать не удалось.

        Обычный `COALESCE(SUM(...), 0)` здесь опасен, и это выяснилось не в
        рассуждении, а на тесте. Ненайденный курс делает произведение `NULL`,
        `SUM` молча выбрасывает такое слагаемое, а `COALESCE` превращает
        результат в ноль — и остаток счёта с пропавшей динарной тратой выходит
        ровно тем же числом, что и до неё. Ошибки нет, есть неправда.

        `COUNT(*) = COUNT(выражение)` отличает «слагаемых не было» от «слагаемое
        не посчиталось»: первое честно даёт ноль, второе — `NULL`, который
        доходит до самого верха и превращается в отказ. Это дублирует
        предварительную загрузку курсов, и намеренно: цена ошибки здесь —
        молчаливо неверные деньги.
        """
        return case(
            (func.count() == func.count(amount), func.coalesce(func.sum(amount), _ZERO)),
            else_=literal(None, MONEY),
        )

    @classmethod
    def _records_sum(cls) -> ColumnElement[Decimal]:
        """Сумма операций счёта в его валюте. Знаковая: расходы уже отрицательны."""
        factor = rate_factor(RecordORM.currency, SourceORM.currency, RecordORM.added_at)
        return (
            select(cls._total(RecordORM.amount * factor))
            .where(
                RecordORM.source_id == SourceORM.id,
                RecordORM.deleted_at.is_(None),
            )
            .correlate(SourceORM)
            .scalar_subquery()
        )

    @classmethod
    def _incoming_transfers_sum(cls) -> ColumnElement[Decimal]:
        """Сумма зачислений, приведённая к валюте принимающего счёта.

        Сумма перевода выражена в валюте счёта-источника — это единственная
        валюта, которую называет пользователь, — поэтому подзапросу нужен сам
        счёт-источник, а не только его идентификатор.
        """
        from_source = aliased(SourceORM, name="from_source")
        factor = rate_factor(from_source.currency, SourceORM.currency, TransferORM.added_at)
        return (
            select(cls._total(TransferORM.amount * factor))
            .select_from(TransferORM)
            .join(from_source, from_source.id == TransferORM.from_source_id)
            .where(
                TransferORM.to_source_id == SourceORM.id,
                TransferORM.deleted_at.is_(None),
            )
            .correlate(SourceORM)
            .scalar_subquery()
        )

    @staticmethod
    def _outgoing_transfers_sum() -> ColumnElement[Decimal]:
        """Сумма списаний. Без конвертации: она уже в валюте этого счёта."""
        return func.coalesce(
            select(func.sum(TransferORM.amount))
            .where(
                TransferORM.from_source_id == SourceORM.id,
                TransferORM.deleted_at.is_(None),
            )
            .correlate(SourceORM)
            .scalar_subquery(),
            _ZERO,
        )
