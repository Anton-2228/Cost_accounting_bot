"""Разбор QR-кода российского фискального чека.

Строка выглядит так::

    t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp=698610272&n=1

`t` — момент покупки, `s` — сумма, `fn` — номер фискального накопителя, `i` —
фискальный документ (в запросах он же `fd`), `fp` — фискальный признак, `n` —
вид расчёта.

Реквизиты берутся разбором query-строки, а не моделью. Старая версия просила
LLM вытащить ФН/ФД/ФП из текста и переклеивала дату строковыми операциями:
лишний платный вызов, недетерминированный результат и падение на любом
отклонении — ради данных, которые лежат в строке готовыми.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl

from checks_service import constants
from checks_service.enums import CheckKind
from checks_service.exceptions import FormatNotSupportedError
from checks_service.formats.base import CheckPreview, ParsedCheck

#: Поля, без которых чек не расшифровать. `n` не обязателен: внешний сервис его
#: не требует, а на части чеков он отсутствует.
_REQUIRED_FIELDS = ("t", "s", "fn", "i", "fp")


class RuFnsQrParser:
    """Парсер QR-кода ФНС."""

    kind = CheckKind.RU_FNS

    def matches(self, qr_raw: str) -> bool:
        """Есть ли в строке все обязательные реквизиты ФНС."""
        fields = self._fields(qr_raw)
        return all(fields.get(name) for name in _REQUIRED_FIELDS)

    def parse(self, qr_raw: str) -> ParsedCheck:
        """Разбирает строку в реквизиты, ключ дедупликации и плашку."""
        fields = self._fields(qr_raw)
        missing = [name for name in _REQUIRED_FIELDS if not fields.get(name)]
        if missing:
            raise FormatNotSupportedError(
                "В QR-коде нет обязательных реквизитов: " + ", ".join(missing)
            )

        # `i` в QR-коде и `fd` в запросе расшифровки — одно и то же поле.
        fn, fd, fp = fields["fn"], fields["i"], fields["fp"]
        moment = fields["t"]
        total = fields["s"]

        return ParsedCheck(
            kind=self.kind,
            qr_raw=qr_raw.strip(),
            external_key=constants.RU_FNS_KEY_SEPARATOR.join((fn, fd, fp)),
            credentials={"fn": fn, "fd": fd, "fp": fp, "t": moment, "s": total},
            preview=CheckPreview(
                total=self._total(total),
                purchased_at=self._purchased_at(moment),
            ),
        )

    @staticmethod
    def _fields(qr_raw: str) -> dict[str, str]:
        """Разбирает строку как набор пар `ключ=значение`."""
        return dict(parse_qsl(qr_raw.strip(), keep_blank_values=True))

    @staticmethod
    def _total(raw: str) -> Decimal | None:
        """Сумма чека из поля `s`.

        Именно `Decimal`, а не `float`: деньги во всей системе десятичные, и
        промежуточный `float` терял бы копейки уже на плашке.
        """
        try:
            return Decimal(raw.replace(",", "."))
        except InvalidOperation:
            return None

    @staticmethod
    def _purchased_at(raw: str) -> datetime | None:
        """Момент покупки из поля `t`.

        Формат уже пригоден и для запроса расшифровки, поэтому склеивать дату
        заново, как делала старая версия, не нужно вовсе.

        Часового пояса в чеке нет, и приписывать ему свой мы не станем: это
        местное время кассы, а плашка только показывает его пользователю.
        """
        for pattern in constants.RU_FNS_DATETIME_FORMATS:
            try:
                return datetime.strptime(raw, pattern)
            except ValueError:
                continue
        return None
