"""Разбор ссылки из QR-кода сербского фискального чека.

Строка выглядит так::

    https://suf.purs.gov.rs/v/?vl=A1lNUVFXR0tDWU1RUVdHS0OLPwEAiz8BAPgiXQAA...

В отличие от ФНС, реквизиты лежат не парами «ключ=значение», а двоичной
структурой в base64 внутри параметра `vl`. Структура открытая: до подписи ПФР в
ней стоят версия, кто затребовал и кто подписал чек, два счётчика, сумма и
время. Смещения — в :mod:`checks_service.constants`.

Отсюда главное свойство формата: **плашка собирается без единого сетевого
вызова**, ровно как у ФНС. Сумма и время известны из самой ссылки, а номер чека
склеивается из тех же байт — и он же служит ключом дедупликации и ключом
запроса позиций.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from checks_service import constants
from checks_service.enums import CheckKind
from checks_service.exceptions import FormatNotSupportedError
from checks_service.formats.base import CheckPreview, ParsedCheck


class SrbSufQrParser:
    """Парсер ссылки на страницу проверки чека ПУРС."""

    kind = CheckKind.SRB_SUF

    def matches(self, qr_raw: str) -> bool:
        """Ссылка ли это на сербский чек и есть ли в ней разбираемый `vl`.

        Декодирование проверяется уже здесь, а не только в `parse`: реестр
        вызывает `parse` лишь после успешного `matches`, и строка «похожа на
        ссылку, но внутри мусор» обязана уйти в общий отказ «формат не
        распознан», а не свалиться исключением из середины разбора.
        """
        return self._header(qr_raw) is not None

    def parse(self, qr_raw: str) -> ParsedCheck:
        """Разбирает ссылку в номер чека, реквизиты и плашку."""
        url = qr_raw.strip()
        header = self._header(url)
        if header is None:
            raise FormatNotSupportedError("В ссылке нет разбираемых данных чека")

        invoice_number = constants.SRB_SUF_KEY_SEPARATOR.join(
            (
                self._text(header, constants.SRB_SUF_REQUESTED_BY_SLICE),
                self._text(header, constants.SRB_SUF_SIGNED_BY_SLICE),
                str(_le(header[constants.SRB_SUF_TX_COUNTER_SLICE])),
            )
        )

        return ParsedCheck(
            kind=self.kind,
            qr_raw=url,
            external_key=invoice_number,
            # Фетчер ходит по самой ссылке: страница чека и есть его источник.
            credentials={"url": url, "invoice_number": invoice_number},
            preview=CheckPreview(
                total=self._total(header),
                purchased_at=self._purchased_at(header),
            ),
        )

    @staticmethod
    def _header(qr_raw: str) -> bytes | None:
        """Двоичный заголовок из `vl` или `None`, если это не сербский чек."""
        parts = urlsplit(qr_raw.strip())
        if parts.scheme != constants.SRB_SUF_SCHEME:
            return None
        # `hostname` вместо `netloc`: последний несёт порт и логин, и сравнение
        # с ними никогда не сойдётся.
        if parts.hostname != constants.SRB_SUF_HOST:
            return None

        values = parse_qs(parts.query).get(constants.SRB_SUF_QUERY_FIELD)
        if not values or not values[0]:
            return None

        try:
            # `validate=False`: сайт кладёт в ссылку обычный base64, но лишний
            # перевод строки при копировании руками ронять разбор не должен.
            decoded = base64.b64decode(_padded(values[0]))
        except (binascii.Error, ValueError):
            return None

        if len(decoded) < constants.SRB_SUF_HEADER_SIZE:
            return None
        return decoded

    @staticmethod
    def _text(header: bytes, where: slice) -> str:
        """Восьмибуквенный идентификатор из заголовка."""
        return header[where].decode("ascii", errors="replace").strip()

    @staticmethod
    def _total(header: bytes) -> Decimal:
        """Сумма чека в динарах.

        Записана в десятитысячных долях и **little-endian**. Деление —
        `Decimal` на целое: промежуточный `float` терял бы пары уже на плашке.
        """
        raw = _le(header[constants.SRB_SUF_TOTAL_AMOUNT_SLICE])
        return Decimal(raw) / constants.SRB_SUF_AMOUNT_SCALE

    @staticmethod
    def _purchased_at(header: bytes) -> datetime:
        """Момент выдачи чека.

        Миллисекунды от эпохи и **big-endian** — в отличие от суммы, лежащей
        рядом little-endian. Время в UTC, и здесь мы его знаем точно: в отличие
        от чека ФНС, где часового пояса нет вовсе и приписывать его было бы
        выдумкой.

        Секунды и миллисекунды разделяются целочисленно: `millis / 1000` дал бы
        `float` и уехал бы в микросекунды мимо на дальних датах.
        """
        millis = _be(header[constants.SRB_SUF_DATE_TIME_SLICE])
        seconds, remainder = divmod(millis, 1000)
        return datetime.fromtimestamp(seconds, tz=UTC).replace(microsecond=remainder * 1000)


def _le(raw: bytes) -> int:
    """Целое, записанное младшим байтом вперёд."""
    return int.from_bytes(raw, byteorder="little")


def _be(raw: bytes) -> int:
    """Целое, записанное старшим байтом вперёд."""
    return int.from_bytes(raw, byteorder="big")


def _padded(value: str) -> str:
    """Достраивает base64 до кратной четырём длины.

    Сайт обрезает последний `=`, и без добавки строка не декодируется вовсе.
    """
    return value + "=" * (-len(value) % 4)
