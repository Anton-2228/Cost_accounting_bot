"""Модели ответов api на стороне бота.

Зеркала схем из `api/responses/`. Дублирование сознательное: общего пакета схем
нет, и заводить его значило бы связать два сервиса на уровне сборки. Плата за
это — правило: **изменилось поле в `api/responses`, меняем и здесь.**

Деньги остаются `Decimal` до самого текста сообщения. Ни одного `float` по пути
от api к пользователю: копейки в отчёте о балансе не должны плыть.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CategoryKind(StrEnum):
    """Вид категории. Знак операции определяется им, а не вводом пользователя."""

    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class EntityStatus(StrEnum):
    """Состояние справочной записи."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class NotificationKind(StrEnum):
    """Вид уведомления о фоновой работе."""

    TABLE_READY = "TABLE_READY"
    IMPORT_ERROR = "IMPORT_ERROR"
    SYNC_FAILED = "SYNC_FAILED"
    ROLLOVER = "ROLLOVER"


class Spreadsheet(BaseModel):
    """Учётная таблица."""

    model_config = ConfigDict(extra="ignore")

    id: int
    google_spreadsheet_id: str | None
    title: str
    reset_day: int
    timezone: str

    @property
    def is_ready(self) -> bool:
        """Документ в Google уже создан.

        Пустой идентификатор — рабочее состояние сразу после `/start`: строки в
        базе есть, а документ создаёт отдельный сервис по задаче из очереди.
        """
        return self.google_spreadsheet_id is not None


class Category(BaseModel):
    """Категория операций."""

    model_config = ConfigDict(extra="ignore")

    id: int
    kind: CategoryKind
    status: EntityStatus
    title: str
    associations: list[str]
    product_types: list[str]


class Source(BaseModel):
    """Счёт."""

    model_config = ConfigDict(extra="ignore")

    id: int
    status: EntityStatus
    title: str
    associations: list[str]
    start_balance: Decimal


class Record(BaseModel):
    """Операция.

    `amount` знаковая: расход отрицателен. Пользователю сумма показывается без
    знака — направление он и так видит по названию категории.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    period_id: int
    category_id: int
    source_id: int
    amount: Decimal
    added_at: date
    notes: str
    from_check: bool = False


class Transfer(BaseModel):
    """Перевод между счетами."""

    model_config = ConfigDict(extra="ignore")

    id: int
    period_id: int
    from_source_id: int
    to_source_id: int
    amount: Decimal
    added_at: date
    notes: str


class UserNotification(BaseModel):
    """Сообщение о фоновой работе, готовое к печати как есть."""

    model_config = ConfigDict(extra="ignore")

    id: int
    kind: NotificationKind
    text: str
