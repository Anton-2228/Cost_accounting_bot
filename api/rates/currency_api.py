"""Курсы валют из `@fawazahmed0/currency-api`.

Это не сервис с квотами, а статические JSON-файлы на CDN: робот раз в сутки
собирает курсы и публикует их версией npm-пакета, у которой тег — дата. Отсюда
свойства, ради которых источник и выбран: ни ключа, ни регистрации, ни лимитов,
и один GET на (база, дата) отдаёт котировки ко всем валютам сразу.

OANDA, которую спрашивали первой, не подошла: публичный эндпоинт её конвертера
отвечает `invalid request` на любые параметры, `labs-api` отдаёт обфусцированный
поток только с текущими курсами и без динара, а настоящий продукт стоит от $450
в месяц и требует аккаунта.

Хостов два, и они независимы. Основной — jsDelivr; резервный раздаёт те же
файлы с Cloudflare Pages. Второй спасает от недоступности именно jsDelivr, а не
от исчезновения самого проекта: против этого работает кэш в БД, в котором курсы
оседают навсегда.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from api.core import constants
from api.core.logging import get_logger
from api.enums import Currency
from api.rates.base import RateUnavailableError

logger = get_logger(__name__)


def parse_rates(payload: Any, base: Currency) -> dict[Currency, Decimal]:
    """Достаёт из ответа котировки известных нам валют.

    Чистая функция: ни сети, ни клиента, поэтому проверяется таблицей примеров.

    Ответ содержит три с лишним сотни валют, из которых нас интересуют четыре.
    Лишние отбрасываются здесь, а не в вызывающем коде: в кэш не должно попадать
    то, что перечисление :class:`~api.enums.currency.Currency` не умеет назвать.

    Числа переводятся в `Decimal` **через строку**. Через `float` курс
    0.00854321 приобретает хвост из двоичного мусора, который затем честно
    ложится в `NUMERIC(24, 12)` и делает разные пересчёты одной суммы
    неодинаковыми.
    """
    if not isinstance(payload, dict):
        raise RateUnavailableError("Источник курсов ответил неожиданной структурой")

    quotes = payload.get(base.value.lower())
    if not isinstance(quotes, dict):
        raise RateUnavailableError(
            "В ответе источника курсов нет запрошенной базовой валюты",
            details={"base": base.value},
        )

    rates: dict[Currency, Decimal] = {}
    for currency in Currency:
        if currency is base:
            # Курс к себе самой всегда единица, в кэше её нет — см.
            # api/orm/exchange_rate.py.
            continue
        raw = quotes.get(currency.value.lower())
        if raw is None:
            continue
        try:
            rate = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            logger.warning("нечисловой курс %s→%s: %r", base, currency, raw)
            continue
        if rate <= 0:
            logger.warning("неположительный курс %s→%s: %s", base, currency, rate)
            continue
        rates[currency] = rate

    if not rates:
        raise RateUnavailableError(
            "Источник курсов не вернул ни одной известной валюты",
            details={"base": base.value},
        )
    return rates


class CurrencyApiProvider:
    """Клиент CDN-раздачи курсов с резервным хостом."""

    def __init__(
        self,
        *,
        base_url: str = constants.CURRENCY_API_BASE_URL,
        path_template: str = constants.CURRENCY_API_PATH_TEMPLATE,
        fallback_url_template: str = constants.CURRENCY_API_FALLBACK_URL_TEMPLATE,
        timeout: float = constants.CURRENCY_API_TIMEOUT_SECONDS,
    ) -> None:
        self._primary_url_template = base_url.rstrip("/") + path_template
        self._fallback_url_template = fallback_url_template
        # follow_redirects: jsDelivr отвечает редиректом на конкретную версию
        # пакета, и без этого вместо курсов приходит пустое тело 301-го.
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def rates_on(self, base: Currency, day: date) -> dict[Currency, Decimal]:
        """Котировки `base` ко всем известным валютам на день `day`."""
        fields = {"day": day.isoformat(), "base": base.value.lower()}
        urls = (
            self._primary_url_template.format(**fields),
            self._fallback_url_template.format(**fields),
        )

        for index, url in enumerate(urls):
            payload = await self._get(url, last=index == len(urls) - 1)
            if payload is not None:
                return parse_rates(payload, base)

        # Недостижимо: последняя попытка либо возвращает тело, либо бросает.
        raise RateUnavailableError("Источник курсов недоступен", details={"day": fields["day"]})

    async def _get(self, url: str, *, last: bool) -> Any | None:
        """Тело ответа, либо `None`, чтобы вызывающий попробовал следующий хост.

        На последней попытке возвращать `None` некуда, поэтому она бросает.
        Молчаливое «курса нет» здесь недопустимо: пропущенный курс превращается
        в `NULL` внутри `SUM` и занижает остаток, не подавая никакого признака.
        """
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as error:
            logger.warning("источник курсов недоступен (%s): %s", url, error)
            if last:
                raise RateUnavailableError("Источник курсов недоступен") from error
            return None

        if response.status_code != httpx.codes.OK:
            logger.warning("источник курсов ответил %s (%s)", response.status_code, url)
            if last:
                raise RateUnavailableError(
                    "Источник курсов ответил ошибкой",
                    details={"status_code": response.status_code},
                )
            return None

        try:
            return response.json()
        except ValueError as error:
            logger.warning("источник курсов ответил не JSON (%s)", url)
            if last:
                raise RateUnavailableError("Источник курсов ответил не JSON") from error
            return None
