"""Приведение суммы к другой валюте внутри SQL-агрегата.

Общее место для двух подсчётов, которым нужна конвертация: остатка счёта
(:mod:`api.repositories.source_repository`) и дневных итогов листа статистики
(:mod:`api.repositories.record_repository`). Выражение одно на оба, потому что
и правило одно: сумма приводится по курсу на день **своей** операции, а не на
сегодня.

Курс берётся из кэша подзапросом. Если строки в кэше нет, подзапрос вернёт
`NULL`, произведение станет `NULL`, а `SUM` молча выбросит слагаемое — итог
занизится, ничем себя не выдав. Поэтому у каждого агрегата есть парный метод
`*_requirements`, собирающий множество нужных троек тем же обходом тех же
таблиц, и вызывать агрегат полагается только после
:meth:`api.services.exchange_rate_service.ExchangeRateService.ensure`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, SQLColumnExpression, case, literal, select

from api.db.column_types import RATE
from api.orm.exchange_rate import ExchangeRateORM

#: Единица в типе курса — множитель для суммы, которая уже в нужной валюте.
#: Явный тип обязателен: с целочисленным литералом арифметика поедет по типам.
ONE = literal(Decimal("1"), RATE)


def rate_factor(
    from_currency: SQLColumnExpression[Any],
    to_currency: SQLColumnExpression[Any],
    day: SQLColumnExpression[Any],
) -> ColumnElement[Decimal]:
    """Множитель перевода `from_currency` → `to_currency` на день `day`.

    Совпадающие валюты дают единицу прямо здесь, не заглядывая в кэш: курса
    валюты к себе самой в таблице нет и быть не должно — см.
    :class:`api.orm.exchange_rate.ExchangeRateORM`.

    Обе валюты и день — колонки, а не значения: множитель вычисляется для
    каждой строки свой, иначе вся затея сводилась бы к одному курсу на всю
    историю. Типы параметров нарочно широкие: сюда приезжают и колонки моделей
    (`InstrumentedAttribute`), и колонки псевдонимов, и литералы, а сузить их до
    `ColumnElement[Currency]` не выходит — он инвариантен по параметру.
    """
    return case(
        (from_currency == to_currency, ONE),
        else_=(
            select(ExchangeRateORM.rate)
            .where(
                ExchangeRateORM.base_currency == from_currency,
                ExchangeRateORM.quote_currency == to_currency,
                ExchangeRateORM.rate_date == day,
            )
            # `correlate_except` обязателен и не является украшательством. Без
            # него SQLAlchemy не догадывается, что `sources` и `records` в
            # условиях — это таблицы объемлющего запроса, и добавляет их в
            # собственный FROM подзапроса. Получается декартово произведение:
            # подзапрос возвращает не одну строку, а по строке на каждый счёт
            # документа, и PostgreSQL валит весь подсчёт с «more than one row
            # returned by a subquery used as an expression».
            .correlate_except(ExchangeRateORM)
            .scalar_subquery()
        ),
    )
