"""Приём чека: распознать формат, расшифровать, сохранить — или отложить.

Порядок шагов — не вкусовщина, а следствие двух решений. Расшифровка платная и
лимитированная, поэтому она откладывается до подтверждения пользователем:
`preview` не делает ни одного внешнего вызова. А чек в `checks` всегда полный,
поэтому `save` пишет туда только после успешной расшифровки — разбору не
придётся уметь работать с получеками.

Чек, который внешний сервис пока не отдал по причине, проходящей со временем
(:data:`RETRYABLE_ERRORS`), не теряется: он откладывается в `pending_checks`.
Оттуда его повторяет пользователь из Mini App (`retry`) или фон (`retry_due`),
и дошедший чек сохраняется тем же путём, что и сразу расшифрованный.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from checks_service import metrics
from checks_service.enums import CheckKind
from checks_service.exceptions import (
    ApiError,
    CheckAlreadySavedError,
    FormatNotSupportedError,
    PendingCheckNotFoundError,
    ReceiptFetchError,
    ReceiptNotFoundError,
    ReceiptNotReadyError,
    SpreadsheetNotFoundError,
)
from checks_service.formats.base import CheckPreview, ParsedCheck
from checks_service.formats.registry import FormatRegistry
from checks_service.logging import get_logger
from checks_service.main_api import ApiGateway, PendingCheck, SavedCheck, Spreadsheet
from checks_service.main_api.pending_checks import notice_body

logger = get_logger(__name__)

#: Отказы внешнего сервиса, которые со временем проходят сами: такой чек не
#: теряется, а откладывается и повторяется. Сейчас это только сербский чек без
#: состава — касса ещё не передала его в налоговую. «Чека нет в базе ФНС» сюда
#: не входит: чаще это испорченный QR, и неделю спрашивать о нём впустую
#: незачем. Включить его — значит дописать класс в этот кортеж.
RETRYABLE_ERRORS: tuple[type[ReceiptFetchError], ...] = (ReceiptNotReadyError,)


@contextmanager
def _fetch_observed(kind: CheckKind) -> Iterator[None]:
    """Измеряет поход во внешний сервис расшифровки.

    Исход различается, потому что различаются и причины: «чека нет в базе
    налоговой» приходит быстро и повтора не заслуживает, а сбой сервиса обычно
    упирается в таймаут, и по одной лишь длительности их не отличить.

    **Порядок `except` существенен.** :class:`ReceiptNotFoundError` и
    :class:`ReceiptNotReadyError` — подклассы :class:`ReceiptFetchError`, и
    стой общий обработчик первым, всякий ненайденный или ещё не переданный
    кассой чек тихо считался бы сбоем сервиса.

    Исключение пробрасывается из любой ветки: замер — наблюдение, а не
    обработка, и решать судьбу отказа он не вправе.
    """
    started = perf_counter()
    outcome = "ok"
    try:
        yield
    except ReceiptNotFoundError:
        outcome = "not_found"
        raise
    except ReceiptNotReadyError:
        outcome = "not_ready"
        raise
    except ReceiptFetchError:
        outcome = "error"
        raise
    except Exception:
        outcome = "unexpected"
        raise
    finally:
        metrics.observe_fetch(kind, outcome, perf_counter() - started)


@dataclass(frozen=True)
class Preview:
    """Плашка: что показать пользователю до нажатия «Добавить»."""

    parsed: ParsedCheck
    spreadsheet_title: str


@dataclass(frozen=True)
class Intake:
    """Результат добавления чека."""

    parsed: ParsedCheck
    saved: SavedCheck


@dataclass(frozen=True)
class Deferred:
    """Чек не получен, но отложен: его повторят позже."""

    parsed: ParsedCheck
    pending: PendingCheck


@dataclass(frozen=True)
class PendingView:
    """Отложенный чек для списка в Mini App: строка api и сводка из QR."""

    pending: PendingCheck
    preview: CheckPreview


class CheckIntakeService:
    """Оркестрация приёма чека."""

    def __init__(self, *, registry: FormatRegistry, api: ApiGateway) -> None:
        self._registry = registry
        self._api = api

    async def preview(self, qr_raw: str, *, telegram_id: int) -> Preview:
        """Распознаёт формат и проверяет, есть ли куда класть чек.

        Единственный запрос здесь — к своему же api за документом
        пользователя. Во внешний сервис расшифровки не ходим: пользователь ещё
        не подтвердил, что чек вообще нужно добавлять.
        """
        parsed = self._registry.parse(qr_raw)
        spreadsheet = await self._spreadsheet(telegram_id)
        # Считается показанная плашка, а не всякая попытка: нераспознанный QR и
        # отсутствие таблицы — отказы, и они уже посчитаны как отказы.
        metrics.observe_preview(telegram_id, parsed.kind)
        return Preview(parsed=parsed, spreadsheet_title=spreadsheet.title)

    async def save(self, qr_raw: str, *, telegram_id: int) -> Intake | Deferred:
        """Расшифровывает чек и сохраняет его целиком — или откладывает.

        Строка разбирается заново, а не берётся из состояния между запросами:
        своего состояния у сервиса нет вовсе, и доверять клиенту разобранные
        реквизиты значило бы позволить ему подменить ключ дедупликации.

        Отказ из :data:`RETRYABLE_ERRORS` не уходит пользователю ошибкой: чек
        откладывается, и его повторят — фон сам, а пользователь из списка.
        """
        parsed = self._registry.parse(qr_raw)
        spreadsheet = await self._spreadsheet(telegram_id)

        try:
            payload = await self._fetch(parsed)
        except RETRYABLE_ERRORS as error:
            pending = await self._api.pending_checks.add(
                spreadsheet.id,
                kind=parsed.kind,
                qr_raw=parsed.qr_raw,
                external_key=parsed.external_key,
                error=error.code,
            )
            logger.info(
                "Чек (%s) отложен в документе %s: %s",
                parsed.kind,
                spreadsheet.id,
                error.code,
            )
            return Deferred(parsed=parsed, pending=pending)

        saved = await self._store(spreadsheet.id, parsed, payload)
        # Успех считается по тому же признаку, что и пишется в журнал: строка в
        # api появилась. Раньше этого места чек в системе не существует.
        metrics.observe_save(telegram_id, parsed.kind)
        return Intake(parsed=parsed, saved=saved)

    async def list_pending(self, *, telegram_id: int) -> list[PendingView]:
        """Отложенные чеки пользователя со сводкой из QR-строки.

        Сводка собирается разбором заново: api хранит только сырьё. Строка,
        которую больше не узнаёт ни один парсер (формат убрали), остаётся в
        списке без сводки — удалить её пользователь всё равно должен мочь.
        """
        spreadsheet = await self._spreadsheet(telegram_id)
        views: list[PendingView] = []
        for pending in await self._api.pending_checks.list_for(spreadsheet.id):
            try:
                preview = self._registry.parse(pending.qr_raw).preview
            except FormatNotSupportedError:
                preview = CheckPreview()
            views.append(PendingView(pending=pending, preview=preview))
        return views

    async def retry(self, pending_id: int, *, telegram_id: int) -> Intake:
        """Ручной повтор отложенного чека.

        Неудача возвращает чек в очередь с новым окном попыток (даже истёкший)
        и уходит пользователю тем же отказом, что и при скане. «Уже добавлен»
        убирает отложенный чек: ждать больше нечего.
        """
        spreadsheet = await self._spreadsheet(telegram_id)
        pending = await self._api.pending_checks.claim(spreadsheet.id, pending_id)
        parsed = self._registry.parse(pending.qr_raw)

        try:
            payload = await self._fetch(parsed)
        except ReceiptFetchError as error:
            await self._api.pending_checks.fail(
                pending.id, error=error.code, manual=True, preview=parsed.preview
            )
            raise

        try:
            saved = await self._store(spreadsheet.id, parsed, payload)
        except CheckAlreadySavedError:
            await self._forget(pending)
            raise
        metrics.observe_save(telegram_id, parsed.kind)
        return Intake(parsed=parsed, saved=saved)

    async def delete_pending(self, pending_id: int, *, telegram_id: int) -> None:
        """Убирает отложенный чек пользователя."""
        spreadsheet = await self._spreadsheet(telegram_id)
        await self._api.pending_checks.delete(spreadsheet.id, pending_id)

    async def retry_due(self) -> int:
        """Фоновый проход: повторяет чеки, которым пора. Возвращает число добавленных.

        Чеки идут по одному, и сбой одного не мешает остальным: захват со
        сроком вернёт упавший в очередь сам.
        """
        added = 0
        for pending in await self._api.pending_checks.claim_due():
            try:
                added += await self._retry_in_background(pending)
            except Exception:
                logger.exception("Фоновый повтор отложенного чека %s не удался", pending.id)
        return added

    async def _retry_in_background(self, pending: PendingCheck) -> bool:
        """Одна фоновая попытка. True — чек добавлен."""
        try:
            parsed = self._registry.parse(pending.qr_raw)
        except FormatNotSupportedError as error:
            await self._api.pending_checks.fail(
                pending.id, error=error.code, manual=False, preview=CheckPreview()
            )
            return False

        try:
            payload = await self._fetch(parsed)
        except ReceiptFetchError as error:
            await self._api.pending_checks.fail(
                pending.id, error=error.code, manual=False, preview=parsed.preview
            )
            return False

        try:
            await self._store(
                pending.spreadsheet_id,
                parsed,
                payload,
                notice=notice_body(parsed.preview),
            )
        except CheckAlreadySavedError:
            await self._forget(pending)
            return False
        except ApiError as error:
            # Api не принял чек (документ отвязан, api лежит). Отчёт о неудаче
            # обязателен: без него строка возвращалась бы в работу каждый срок
            # аренды и не истекла бы никогда.
            await self._api.pending_checks.fail(
                pending.id, error=error.code, manual=False, preview=parsed.preview
            )
            return False
        return True

    async def _fetch(self, parsed: ParsedCheck) -> dict[str, Any]:
        """Поход во внешний сервис под замером."""
        with _fetch_observed(parsed.kind):
            return await self._registry.fetcher_for(parsed.kind).fetch(parsed)

    async def _store(
        self,
        spreadsheet_id: int,
        parsed: ParsedCheck,
        payload: dict[str, Any],
        *,
        notice: dict[str, str] | None = None,
    ) -> SavedCheck:
        """Сохраняет расшифрованный чек; api заодно уберёт его из отложенных."""
        saved = await self._api.checks.save(
            spreadsheet_id,
            kind=parsed.kind,
            qr_raw=parsed.qr_raw,
            external_key=parsed.external_key,
            raw_payload=payload,
            fetched_at=datetime.now(UTC),
            notice=notice,
        )
        logger.info("Чек %s (%s) добавлен в документ %s", saved.id, parsed.kind, spreadsheet_id)
        return saved

    async def _forget(self, pending: PendingCheck) -> None:
        """Убирает отложенный чек, который уже есть в таблице."""
        with suppress(PendingCheckNotFoundError):
            await self._api.pending_checks.delete(pending.spreadsheet_id, pending.id)

    async def _spreadsheet(self, telegram_id: int) -> Spreadsheet:
        """Документ пользователя или отказ «таблица не создана»."""
        spreadsheet = await self._api.spreadsheets.get_by_telegram(telegram_id)
        if spreadsheet is None:
            raise SpreadsheetNotFoundError(
                "Сначала создайте таблицу командой /start в боте"
            )
        return spreadsheet
