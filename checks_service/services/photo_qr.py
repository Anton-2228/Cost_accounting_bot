"""QR-строка с фотографии чека: zxing, а если он не справился — модель.

Сначала QR читает zxing: бесплатно и мгновенно. Не нашёл — фото уходит в
сайдкар qr_vision (pi + модель через OpenRouter). Модели верить на слово нельзя:
её строка годится, только если её узнаёт реестр форматов, а дальше её всё равно
проверяет пользователь на плашке и налоговая при расшифровке.
"""

from __future__ import annotations

import anyio

from checks_service import metrics
from checks_service.exceptions import ApiError, QrNotFoundError, SpreadsheetNotFoundError
from checks_service.formats.registry import FormatRegistry
from checks_service.logging import get_logger
from checks_service.main_api import ApiGateway
from checks_service.qr_vision import QrVisionClient
from checks_service.services.photo_decoder import decode_qr_codes, image_mime_type

logger = get_logger(__name__)


class PhotoQrService:
    """Находит строку QR чека на фотографии."""

    def __init__(
        self,
        *,
        registry: FormatRegistry,
        api: ApiGateway,
        qr_vision: QrVisionClient | None,
    ) -> None:
        self._registry = registry
        self._api = api
        #: `None` — фолбек выключен в настройках.
        self._qr_vision = qr_vision

    async def decode(self, data: bytes, *, telegram_id: int) -> str:
        """Строка QR чека; не нашлась — :class:`QrNotFoundError`.

        Если QR несколько, берётся первый, который узнаёт реестр форматов
        (рядом с фискальным часто напечатан рекламный); не узнал ни один —
        первый найденный, и плашка честно ответит `format_not_supported`.
        """
        codes = await anyio.to_thread.run_sync(decode_qr_codes, data)
        if codes:
            return next((code for code in codes if self._registry.recognises(code)), codes[0])
        # Снимок прочитан (иначе `decode_qr_codes` уже бросил бы), так что тип
        # известен; формат, который модели не показать, — без фолбека.
        mime_type = image_mime_type(data)
        if self._qr_vision is None or mime_type is None:
            raise QrNotFoundError("На фотографии не найден QR-код", details={"bytes": len(data)})
        return await self._fallback(data, mime_type=mime_type, telegram_id=telegram_id)

    async def _fallback(self, data: bytes, *, mime_type: str, telegram_id: int) -> str:
        """Просит модель. Любая неудача — тот же `qr_not_found`, что и без неё."""
        assert self._qr_vision is not None  # noqa: S101 — проверено вызывающим

        # Таблица нужна до вызова: расход пишется на неё, а без неё и чек
        # класть некуда — платить за модель незачем.
        spreadsheet = await self._api.spreadsheets.get_by_telegram(telegram_id)
        if spreadsheet is None:
            raise SpreadsheetNotFoundError("У пользователя нет учётной таблицы")

        result = await self._qr_vision.decode(data, mime_type=mime_type)
        if result is None:
            metrics.observe_qr_fallback("error")
            raise QrNotFoundError("QR не найден, фолбек недоступен", details={"fallback": "error"})

        # Расход пишется до проверки ответа: деньги потрачены в любом случае.
        # Не записался — это не повод отказывать пользователю.
        if result.usage is not None:
            try:
                await self._api.llm_usages.record_qr_fallback(spreadsheet.id, result.usage)
            except ApiError:
                logger.exception("Не удалось записать расход фолбека QR")

        if result.qr is None:
            metrics.observe_qr_fallback("empty")
            raise QrNotFoundError("QR не прочитала и модель", details={"fallback": "empty"})
        if not self._registry.recognises(result.qr):
            metrics.observe_qr_fallback("unrecognised")
            logger.warning("Модель вернула строку незнакомого формата: %r", result.qr[:120])
            raise QrNotFoundError("Модель вернула не чек", details={"fallback": "unrecognised"})

        metrics.observe_qr_fallback("ok")
        logger.info("QR прочитан моделью, telegram_id=%s", telegram_id)
        return result.qr
