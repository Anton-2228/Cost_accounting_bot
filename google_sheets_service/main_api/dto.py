"""Структуры данных, приезжающие из api.

Зеркала схем `api/responses`. Дублирование намеренно: общего пакета схем нет, и
затаскивать сюда `api` целиком ради десятка полей значило бы притащить вместе с
ним SQLAlchemy и подключение к Postgres. **Если поле меняется в
`api/responses`, его нужно поменять и здесь.**

Разбор явный, без pydantic: конвертация в одном месте и видна глазами. Деньги
приезжают строками (pydantic сериализует `Decimal` именно так) и становятся
`Decimal` без промежуточного `float` — иначе копейки терялись бы по дороге к
листу.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _decimal(value: Any) -> Decimal:
    """Превращает пришедшее из JSON число в `Decimal` без потери точности.

    Строка — обычный случай. `float` терпится на случай, если поле когда-нибудь
    перестанет быть `Decimal` на стороне api, но идёт через `repr`: `Decimal(0.1)`
    даёт хвост из семнадцати знаков, `Decimal(repr(0.1))` — ровно `0.1`.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


@dataclass(frozen=True)
class SyncTask:
    """Задача очереди: какой лист какого документа устарел."""

    id: int
    spreadsheet_id: int
    kind: str
    target: str
    period_id: int | None
    #: Метка версии. Возвращается в `complete` без изменений: если за время
    #: работы лист успели изменить снова, значение разойдётся и задача
    #: останется в очереди.
    requested_at: datetime
    attempts: int

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> SyncTask:
        """Собирает задачу из ответа api."""
        return cls(
            id=int(body["id"]),
            spreadsheet_id=int(body["spreadsheet_id"]),
            kind=str(body["kind"]),
            target=str(body["target"]),
            period_id=None if body["period_id"] is None else int(body["period_id"]),
            requested_at=datetime.fromisoformat(body["requested_at"]),
            attempts=int(body["attempts"]),
        )


@dataclass(frozen=True)
class Spreadsheet:
    """Учётная таблица. Пустой `google_spreadsheet_id` — документ ещё не создан."""

    id: int
    google_spreadsheet_id: str | None
    title: str
    reset_day: int
    timezone: str

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Spreadsheet:
        """Собирает документ из ответа api."""
        google_id = body["google_spreadsheet_id"]
        return cls(
            id=int(body["id"]),
            google_spreadsheet_id=None if google_id is None else str(google_id),
            title=str(body["title"]),
            reset_day=int(body["reset_day"]),
            timezone=str(body["timezone"]),
        )


@dataclass(frozen=True)
class Access:
    """Доступ к документу. `granted_at is None` — выдать предстоит."""

    id: int
    email: str
    role: str
    granted_at: datetime | None

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Access:
        """Собирает доступ из ответа api."""
        granted_at = body["granted_at"]
        return cls(
            id=int(body["id"]),
            email=str(body["email"]),
            role=str(body["role"]),
            granted_at=None if granted_at is None else datetime.fromisoformat(granted_at),
        )


@dataclass(frozen=True)
class Category:
    """Категория расхода или дохода."""

    id: int
    kind: str
    status: str
    title: str
    associations: list[str]
    product_types: list[str]

    @property
    def is_income(self) -> bool:
        """Категория дохода."""
        return self.kind == "INCOME"

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Category:
        """Собирает категорию из ответа api."""
        return cls(
            id=int(body["id"]),
            kind=str(body["kind"]),
            status=str(body["status"]),
            title=str(body["title"]),
            associations=[str(item) for item in body["associations"]],
            product_types=[str(item) for item in body["product_types"]],
        )


@dataclass(frozen=True)
class Source:
    """Счёт. Текущего баланса здесь нет — он не хранится, а считается."""

    id: int
    status: str
    title: str
    associations: list[str]
    start_balance: Decimal

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Source:
        """Собирает счёт из ответа api."""
        return cls(
            id=int(body["id"]),
            status=str(body["status"]),
            title=str(body["title"]),
            associations=[str(item) for item in body["associations"]],
            start_balance=_decimal(body["start_balance"]),
        )


@dataclass(frozen=True)
class SourceBalance:
    """Счёт вместе с посчитанным балансом."""

    source_id: int
    title: str
    start_balance: Decimal
    balance: Decimal

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> SourceBalance:
        """Собирает баланс из ответа api."""
        return cls(
            source_id=int(body["source_id"]),
            title=str(body["title"]),
            start_balance=_decimal(body["start_balance"]),
            balance=_decimal(body["balance"]),
        )


@dataclass(frozen=True)
class Period:
    """Учётный период. Границы полуинтервальные: день `end_date` не входит."""

    id: int
    start_date: date
    end_date: date
    status: str

    @property
    def is_open(self) -> bool:
        """Период ещё не закрыт ролловером."""
        return self.status == "OPEN"

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Period:
        """Собирает период из ответа api."""
        return cls(
            id=int(body["id"]),
            start_date=date.fromisoformat(body["start_date"]),
            end_date=date.fromisoformat(body["end_date"]),
            status=str(body["status"]),
        )


@dataclass(frozen=True)
class Record:
    """Операция. Сумма знаковая: расход отрицателен, доход положителен."""

    id: int
    period_id: int
    category_id: int
    source_id: int
    amount: Decimal
    added_at: date
    notes: str
    product_name: str | None
    product_type: str | None
    from_check: bool

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Record:
        """Собирает операцию из ответа api."""
        product_name = body["product_name"]
        product_type = body["product_type"]
        return cls(
            id=int(body["id"]),
            period_id=int(body["period_id"]),
            category_id=int(body["category_id"]),
            source_id=int(body["source_id"]),
            amount=_decimal(body["amount"]),
            added_at=date.fromisoformat(body["added_at"]),
            notes=str(body["notes"]),
            product_name=None if product_name is None else str(product_name),
            product_type=None if product_type is None else str(product_type),
            from_check=bool(body["from_check"]),
        )


@dataclass(frozen=True)
class Transfer:
    """Перевод между счетами. Сумма строго положительна: направление задают счета."""

    id: int
    period_id: int
    from_source_id: int
    to_source_id: int
    amount: Decimal
    added_at: date
    notes: str

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Transfer:
        """Собирает перевод из ответа api."""
        return cls(
            id=int(body["id"]),
            period_id=int(body["period_id"]),
            from_source_id=int(body["from_source_id"]),
            to_source_id=int(body["to_source_id"]),
            amount=_decimal(body["amount"]),
            added_at=date.fromisoformat(body["added_at"]),
            notes=str(body["notes"]),
        )


@dataclass(frozen=True)
class CategoryDailyTotal:
    """Сумма одной категории за один день периода."""

    category_id: int
    day: date
    total: Decimal

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> CategoryDailyTotal:
        """Собирает дневной итог из ответа api."""
        return cls(
            category_id=int(body["category_id"]),
            day=date.fromisoformat(body["day"]),
            total=_decimal(body["total"]),
        )


@dataclass(frozen=True)
class SheetMapping:
    """Где физически лежит лист. Наличие записи означает «лист уже создан»."""

    id: int
    target: str
    period_id: int | None
    google_sheet_id: int
    title: str

    @property
    def key(self) -> tuple[str, int | None]:
        """Ключ адресата: сочетание цели и периода."""
        return (self.target, self.period_id)

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> SheetMapping:
        """Собирает соответствие из ответа api."""
        return cls(
            id=int(body["id"]),
            target=str(body["target"]),
            period_id=None if body["period_id"] is None else int(body["period_id"]),
            google_sheet_id=int(body["google_sheet_id"]),
            title=str(body["title"]),
        )


@dataclass(frozen=True)
class ImportResult:
    """Что сделал импорт или почему не сделал ничего.

    Заполненный `error` — не сбой задачи: разбор листа не удался, но api уже
    положил русский текст в уведомления пользователю, и повторять чтение того же
    листа бессмысленно.
    """

    error: str | None
    created: int
    updated: int
    deleted: int

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> ImportResult:
        """Собирает результат импорта из ответа api."""
        error = body["error"]
        return cls(
            error=None if error is None else str(error),
            created=int(body["created"]),
            updated=int(body["updated"]),
            deleted=int(body["deleted"]),
        )
