"""Производная величина: текущий баланс счёта."""

from __future__ import annotations

from pydantic import BaseModel

from api.core.types import SignedMoneyDecimal


class SourceBalance(BaseModel):
    """Счёт вместе с посчитанным балансом.

    Отдельная модель, а не поле в :class:`api.domain.source.Source`, именно
    потому, что баланс не хранится: это результат агрегата, а не свойство
    строки. Модель без поля не даст случайно «сохранить» баланс обратно в БД,
    как это делал прежний `current_balance`.

    Баланс знаковый: счёт может уйти в минус.
    """

    source_id: int
    title: str
    start_balance: SignedMoneyDecimal
    balance: SignedMoneyDecimal
