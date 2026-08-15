"""Точка расширения: разбор QR-строки и получение расшифровки.

Две роли разделены намеренно. `QrParser` — чистая функция «строка → реквизиты»:
он ничего не знает про сеть, и потому проверяется таблицей примеров. Весь
ввод-вывод собран в `ReceiptFetcher`. Сербский чек добавится парой файлов
рядом, и ни один существующий трогать не придётся.

Между ними ездит :class:`ParsedCheck` — единственное, что фетчер получает от
парсера. Реквизиты в нём лежат словарём: у каждого формата они свои, и
перечислять их полями общей модели значило бы вписать в общее место содержимое
одного конкретного формата.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from checks_service.enums import CheckKind


@dataclass(frozen=True)
class CheckPreview:
    """То, что можно показать пользователю **до** расшифровки.

    Собирается из самой QR-строки: пока пользователь не нажал «Добавить»,
    внешний сервис не зовётся, а платный лимит не тратится. Поля необязательные
    — формат может не нести ни суммы, ни времени, и плашка тогда покажет только
    название формата.
    """

    total: Decimal | None = None
    purchased_at: datetime | None = None


@dataclass(frozen=True)
class ParsedCheck:
    """Результат разбора QR-строки."""

    kind: CheckKind
    qr_raw: str
    #: Ключ дедупликации в терминах формата (ФНС: «ФН:ФД:ФП»).
    external_key: str
    #: Реквизиты для фетчера. Состав известен только паре «парсер — фетчер».
    credentials: dict[str, str] = field(default_factory=dict)
    preview: CheckPreview = field(default_factory=CheckPreview)


@runtime_checkable
class QrParser(Protocol):
    """Разбирает QR-строку одного формата. Чистая функция, без ввода-вывода."""

    kind: CheckKind

    def matches(self, qr_raw: str) -> bool:
        """Похожа ли строка на чек этого формата."""
        ...

    def parse(self, qr_raw: str) -> ParsedCheck:
        """Разбирает строку. Вызывается только после успешного `matches`."""
        ...


@runtime_checkable
class ReceiptFetcher(Protocol):
    """Получает расшифровку чека у внешнего сервиса. Здесь весь ввод-вывод."""

    async def fetch(self, parsed: ParsedCheck) -> dict[str, Any]:
        """Возвращает ответ внешнего сервиса целиком, как он пришёл."""
        ...

    async def aclose(self) -> None:
        """Закрывает соединения."""
        ...
