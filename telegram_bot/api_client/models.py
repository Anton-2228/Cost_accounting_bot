"""Модели ответов api на стороне бота.

Зеркала схем из `api/responses/`. Дублирование сознательное: общего пакета схем
нет, и заводить его значило бы связать два сервиса на уровне сборки. Плата за
это — правило: **изменилось поле в `api/responses`, меняем и здесь.**

Деньги остаются `Decimal` до самого текста сообщения. Ни одного `float` по пути
от api к пользователю: копейки в отчёте о балансе не должны плыть.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

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
    IMPORT_OK = "IMPORT_OK"
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
    #: Номер чека, из которого распознана позиция. Бот его не печатает, но поле
    #: держится в зеркале схемы api: расхождение мирно живёт до первого
    #: обращения, а потом обходится дороже.
    check_id: int | None = None


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


class Check(BaseModel):
    """Сохранённый чек: сырьё и отметка о разборе.

    `raw_payload` — ответ внешнего сервиса целиком, и разбирает его бот:
    `telegram_bot.checks.ReceiptExtractor`. Api его не интерпретирует вовсе,
    поэтому здесь он и остаётся словарём, а не набором полей.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    qr_raw: str
    raw_payload: dict[str, Any]
    fetched_at: datetime
    processed_at: datetime | None = None


class CashedRecord(BaseModel):
    """Выученное соответствие «товар → тип».

    Кэш документа, а не бота: единственный источник истины по нему — api.
    Благодаря ему модель не спрашивают о товаре, который уже встречался.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    product_name: str
    product_type: str


class UserNotification(BaseModel):
    """Сообщение о фоновой работе, готовое к печати как есть."""

    model_config = ConfigDict(extra="ignore")

    id: int
    kind: NotificationKind
    text: str
