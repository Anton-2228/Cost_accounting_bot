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


class Currency(StrEnum):
    """Валюта суммы.

    Зеркало `api.enums.Currency`. Список закрыт и меняется только вместе с
    миграцией, поэтому копия здесь дешевле похода в api за справочником,
    который не может измениться между запросами.
    """

    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"
    RSD = "RSD"


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


class LlmOperation(StrEnum):
    """О чём спрашивали модель. Различает две стадии разбора чека."""

    SUGGEST_PRODUCT_TYPES = "SUGGEST_PRODUCT_TYPES"
    SUGGEST_CATEGORIES = "SUGGEST_CATEGORIES"


class LlmEntityKind(StrEnum):
    """К строке какой таблицы относится замер обращения к модели."""

    CHECK = "CHECK"


class Spreadsheet(BaseModel):
    """Учётная таблица."""

    model_config = ConfigDict(extra="ignore")

    id: int
    google_spreadsheet_id: str | None
    title: str
    reset_day: int
    timezone: str
    #: Метка отвязывания. У живой таблицы пуста; заполнена — только в истории
    #: пользователя, единственном месте, где отвязанные вообще показываются.
    deleted_at: datetime | None = None

    @property
    def is_unlinked(self) -> bool:
        """Таблица отвязана от бота.

        Учёт по ней не ведут, но записи и траты на модель остались: отвязывание
        мягкое.
        """
        return self.deleted_at is not None

    @property
    def is_ready(self) -> bool:
        """Документ в Google уже создан.

        Пустой идентификатор — рабочее состояние сразу после `/start`: строки в
        базе есть, а документ создаёт отдельный сервис по задаче из очереди.

        Пустая строка считается таким же «ещё нет», как и `None`. Api пишет
        сюда `NULL`, но проверка на одно только `None` означала бы, что пустая
        строка — это готовность: бот пустил бы владельца в меню и собрал бы ему
        ссылку на документ с пустым идентификатором.
        """
        return bool(self.google_spreadsheet_id)


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
    currency: Currency
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
    currency: Currency
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


class PeriodStatus(StrEnum):
    """Состояние учётного периода."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Period(BaseModel):
    """Учётный «месяц» документа: полуинтервал ``[start_date, end_date)``.

    `end_date` **исключительна**: день, равный ей, относится уже к следующему
    периоду. Границы — даты в часовом поясе документа, а не моменты времени.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    start_date: date
    end_date: date
    status: PeriodStatus

    def contains(self, day: date) -> bool:
        """Относится ли день к этому периоду."""
        return self.start_date <= day < self.end_date


class LlmUsage(BaseModel):
    """Записанный замер одного обращения к модели.

    Тёзка `telegram_bot.ai.LlmUsage`, и это разные вещи: там — то, что ответил
    провайдер прямо сейчас, здесь — то, что об этом сохранено в базе.

    `cost` допускает `None`, и это «неизвестно», а не «бесплатно»: стоимость
    приезжает от провайдера и приходит не всегда. Считать пустое нулём значит
    занижать сумму ровно на неизвестное.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    operation: LlmOperation
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: Decimal | None = None
    created_at: datetime
