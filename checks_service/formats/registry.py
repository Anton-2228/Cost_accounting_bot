"""Реестр форматов: подбор парсера по строке и фетчера по виду чека."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from checks_service.enums import CheckKind
from checks_service.exceptions import FormatNotSupportedError
from checks_service.formats.base import ParsedCheck, QrParser, ReceiptFetcher
from checks_service.logging import get_logger

logger = get_logger(__name__)

#: Сколько символов нераспознанной строки уходит в журнал. Достаточно, чтобы
#: увидеть схему, хост и начало параметра — то есть всё, по чему принимается
#: решение, — и мало, чтобы не выписывать в журнал чек целиком.
_UNRECOGNISED_LOG_LENGTH = 120


class FormatRegistry:
    """Связывает парсеры и фетчеры, оставаясь единственным, кто знает про оба.

    Именно поэтому распознавание формата живёт на сервере: фронт отдаёт строку и
    получает готовую плашку, не зная ни одного формата. Сербский чек появится
    здесь одной строкой в списке — и заработает без правки JS.
    """

    def __init__(
        self,
        parsers: Iterable[QrParser],
        fetchers: Mapping[CheckKind, ReceiptFetcher],
    ) -> None:
        self._parsers = tuple(parsers)
        self._fetchers = dict(fetchers)

    def parse(self, qr_raw: str) -> ParsedCheck:
        """Разбирает строку первым подошедшим парсером."""
        text = qr_raw.strip()
        for parser in self._parsers:
            if parser.matches(text):
                return parser.parse(text)

        # Начало строки уходит в журнал. Без него «не удалось распознать чек» —
        # тупик: со стороны пользователя это одно и то же сообщение и когда он
        # отсканировал штрихкод товара, и когда касса напечатала ссылку не так,
        # как мы ждём. Отличить одно от другого можно только увидев строку.
        logger.warning(
            "Формат чека не распознан, начало строки: %r (всего символов: %s)",
            text[:_UNRECOGNISED_LOG_LENGTH],
            len(text),
        )
        raise FormatNotSupportedError("Не удалось распознать формат чека")

    def fetcher_for(self, kind: CheckKind) -> ReceiptFetcher:
        """Возвращает фетчер вида чека.

        Отсутствие фетчера при живом парсере — ошибка сборки, а не входных
        данных: распознать формат и не уметь его расшифровать бессмысленно.
        """
        fetcher = self._fetchers.get(kind)
        if fetcher is None:  # pragma: no cover — ловится при сборке приложения
            raise RuntimeError(f"Для формата {kind} не задан способ расшифровки")
        return fetcher

    async def aclose(self) -> None:
        """Закрывает соединения всех фетчеров."""
        for fetcher in self._fetchers.values():
            await fetcher.aclose()
