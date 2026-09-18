"""Приём чека: распознать формат, расшифровать, сохранить.

Порядок шагов — не вкусовщина, а следствие двух решений. Расшифровка платная и
лимитированная, поэтому она откладывается до подтверждения пользователем:
`preview` не делает ни одного внешнего вызова. А чек в БД всегда полный,
поэтому `save` пишет в api только после успешной расшифровки — промежуточного
состояния «чек добавлен, но не расшифрован» не существует, и разбору не придётся
уметь работать с получеками.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

from checks_service import metrics
from checks_service.enums import CheckKind
from checks_service.exceptions import (
    ReceiptFetchError,
    ReceiptNotFoundError,
    ReceiptNotReadyError,
    SpreadsheetNotFoundError,
)
from checks_service.formats.base import ParsedCheck
from checks_service.formats.registry import FormatRegistry
from checks_service.logging import get_logger
from checks_service.main_api import ApiGateway, SavedCheck, Spreadsheet

logger = get_logger(__name__)


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

    async def save(self, qr_raw: str, *, telegram_id: int) -> Intake:
        """Расшифровывает чек и сохраняет его целиком.

        Строка разбирается заново, а не берётся из состояния между запросами:
        своего состояния у сервиса нет вовсе, и доверять клиенту разобранные
        реквизиты значило бы позволить ему подменить ключ дедупликации.
        """
        parsed = self._registry.parse(qr_raw)
        spreadsheet = await self._spreadsheet(telegram_id)

        with _fetch_observed(parsed.kind):
            payload = await self._registry.fetcher_for(parsed.kind).fetch(parsed)

        saved = await self._api.checks.save(
            spreadsheet.id,
            kind=parsed.kind,
            qr_raw=parsed.qr_raw,
            external_key=parsed.external_key,
            raw_payload=payload,
            fetched_at=datetime.now(UTC),
        )
        # Успех считается по тому же признаку, что и пишется в журнал: строка в
        # api появилась. Раньше этого места чек в системе не существует.
        metrics.observe_save(telegram_id, parsed.kind)
        logger.info(
            "Чек %s (%s) добавлен в документ %s",
            saved.id,
            parsed.kind,
            spreadsheet.id,
        )
        return Intake(parsed=parsed, saved=saved)

    async def _spreadsheet(self, telegram_id: int) -> Spreadsheet:
        """Документ пользователя или отказ «таблица не создана»."""
        spreadsheet = await self._api.spreadsheets.get_by_telegram(telegram_id)
        if spreadsheet is None:
            raise SpreadsheetNotFoundError(
                "Сначала создайте таблицу командой /start в боте"
            )
        return spreadsheet
