"""Расшифровка сербского чека со страницы ПУРС.

Сербский чек, в отличие от российского, не отдаётся одним JSON. Его приходится
собирать самим из трёх источников:

* страница чека на сербском — значения полей и текст журнала;
* та же страница на английском — те же значения, но переведённые сайтом;
* `POST /specifications` — позиции чека, которых в HTML нет вовсе: страница
  подгружает их отдельным запросом, и мы делаем ровно то же.

Отсюда три решения, каждое из которых стоит назвать:

* **позиции запрашиваются один раз.** Ответ `/specifications` от языка не
  зависит — проверено с обеими куками, — и второй запрос ради той же копии был
  бы платой без покупки;
* **язык переключается кукой** `localization`. Ни `Accept-Language`, ни параметр
  запроса на страницу не влияют, оба молча игнорируются;
* **суммы кладутся строками.** JSON здесь собираем мы, а не переписываем чужой,
  и заводить в нём `float` там, где по всей системе деньги десятичные, незачем.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from checks_service import constants
from checks_service.exceptions import ReceiptFetchError, ReceiptNotFoundError
from checks_service.formats.base import ParsedCheck
from checks_service.formats.srb_suf import labels
from checks_service.logging import get_logger

logger = get_logger(__name__)

#: Токен запроса позиций. Лежит в инлайновом `<script>`, куда его кладёт сама
#: страница, и без него `/specifications` отвечает отказом — проверено.
_TOKEN_PATTERN = re.compile(r"viewModel\.Token\('([^']+)'\)")

#: Идентификатор блока для печати: только там есть название юрлица.
_PRINT_BLOCK_ID = "PrintInvoice"


class SufFetcher:
    """Клиент страницы проверки чеков `suf.purs.gov.rs`."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Клиент страницы чеков.

        `transport` подменяется только в тестах. Шов именно здесь, а не на
        уровне всего фетчера: разбор HTML — самая хрупкая часть формата, и
        подменять целиком объект, внутри которого он живёт, значило бы не
        проверять его вовсе.
        """
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    async def aclose(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.aclose()

    async def fetch(self, parsed: ParsedCheck) -> dict[str, Any]:
        """Собирает расшифровку чека в двух языковых версиях.

        Частичного результата не бывает: любой сбой на любом из трёх запросов —
        исключение, и в БД не попадает ничего. Чек там всегда полный, иначе
        разбору пришлось бы уметь работать с получеками.
        """
        url = parsed.credentials["url"]
        invoice_number = parsed.credentials["invoice_number"]

        sr_page = await self._page(url, constants.SRB_SUF_LOCALE_SR)
        en_page = await self._page(url, constants.SRB_SUF_LOCALE_EN)
        items = await self._items(invoice_number, self._token(sr_page))

        return {
            labels.URL_FIELD: url,
            labels.INVOICE_NUMBER_FIELD: invoice_number,
            labels.SR_FIELD: self._version(sr_page, items, constants.SRB_SUF_LOCALE_SR),
            labels.EN_FIELD: self._version(en_page, items, constants.SRB_SUF_LOCALE_EN),
        }

    # ---- Сеть ----

    async def _page(self, url: str, locale: str) -> BeautifulSoup:
        """Страница чека на указанном языке."""
        # Кука ставится заголовком, а не через `cookies=`: у клиента своя
        # банка, она переживает запрос, и язык второй страницы зависел бы от
        # того, что сайт положил в неё на первой.
        try:
            response = await self._client.get(
                url,
                headers={"Cookie": f"{constants.SRB_SUF_LOCALE_COOKIE}={locale}"},
            )
        except httpx.HTTPError as error:
            logger.warning("Страница чека ПУРС недоступна: %s", error)
            raise ReceiptFetchError("Сервис проверки чеков недоступен") from error

        # 400 сайт отдаёт и на несуществующий чек, и на непрошедшую подпись, с
        # пустым телом в обоих случаях. Различить их нельзя, и текст отказа
        # обязан покрывать оба: повтор в любом из них даст тот же ответ.
        if response.status_code == httpx.codes.BAD_REQUEST:
            raise ReceiptNotFoundError(
                "Такого чека нет в базе налоговой Сербии или его подпись не сходится"
            )
        if response.status_code != httpx.codes.OK:
            logger.warning("Страница чека ПУРС ответила %s", response.status_code)
            raise ReceiptFetchError(
                "Сервис проверки чеков ответил ошибкой",
                details={"status_code": response.status_code},
            )
        return BeautifulSoup(response.text, "lxml")

    async def _items(self, invoice_number: str, token: str) -> list[dict[str, Any]]:
        """Позиции чека. Запрашиваются один раз: от языка они не зависят."""
        try:
            response = await self._client.post(
                f"{self._base_url}{constants.SRB_SUF_SPECIFICATIONS_PATH}",
                data={"invoiceNumber": invoice_number, "token": token},
            )
        except httpx.HTTPError as error:
            logger.warning("Позиции чека ПУРС недоступны: %s", error)
            raise ReceiptFetchError("Сервис проверки чеков недоступен") from error

        if response.status_code != httpx.codes.OK:
            raise ReceiptFetchError(
                "Сервис проверки чеков не отдал позиции",
                details={"status_code": response.status_code},
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise ReceiptFetchError("Сервис проверки чеков ответил не JSON") from error

        if not isinstance(payload, dict) or not payload.get("success"):
            raise ReceiptFetchError("Сервис проверки чеков не отдал позиции")

        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise ReceiptFetchError("Позиции чека пришли неожиданной структурой")
        return [item for item in raw_items if isinstance(item, dict)]

    @staticmethod
    def _token(page: BeautifulSoup) -> str:
        """Токен запроса позиций из инлайнового скрипта страницы."""
        found = _TOKEN_PATTERN.search(page.decode())
        if found is None:
            raise ReceiptFetchError("На странице чека нет ключа для запроса позиций")
        return found.group(1)

    # ---- Сборка одной языковой версии ----

    @classmethod
    def _version(
        cls,
        page: BeautifulSoup,
        items: list[dict[str, Any]],
        locale: str,
    ) -> dict[str, Any]:
        """Одна языковая версия чека целиком.

        Порядок ключей повторяет порядок полей на странице: чек в JSON читается
        сверху вниз так же, как на экране.
        """
        version: dict[str, Any] = {}

        for element_id, label in labels.SPAN_FIELDS:
            value = cls._by_id(page, element_id)
            if not value:
                continue
            if element_id in labels.MONEY_SPAN_IDS:
                value = _decimal_point(value)
            version[label.of(locale)] = value

        print_block = page.find(id=_PRINT_BLOCK_ID)
        for label in labels.PRINT_FIELDS:
            value = cls._from_print_block(print_block, label.of(locale))
            if value:
                version[label.of(locale)] = value

        version[labels.SPECIFICATION.of(locale)] = [cls._item(item, locale) for item in items]

        journal = cls._journal(page)
        if journal:
            version[labels.JOURNAL.of(locale)] = journal
        return version

    @staticmethod
    def _by_id(page: BeautifulSoup, element_id: str) -> str:
        """Текст элемента по `id`, схлопнутый в одну строку.

        Схлопывание обязательно: разметка страницы кладёт значение на отдельной
        строке с отступом в тридцать пробелов, и без него в JSON уехал бы этот
        отступ вместе со значением.
        """
        element = page.find(id=element_id)
        return _collapse(element.get_text()) if isinstance(element, Tag) else ""

    @staticmethod
    def _from_print_block(block: Any, label: str) -> str:
        """Значение из блока для печати по подписи внутри `<strong>`.

        Здесь адресоваться по `id` нельзя — их в блоке нет, — поэтому подпись и
        служит якорем. Двоеточие приписывается: на странице оно часть подписи, а
        в имени ключа ему делать нечего.
        """
        if not isinstance(block, Tag):
            return ""
        for strong in block.find_all("strong"):
            if _collapse(strong.get_text()) != f"{label}:":
                continue
            value = strong.find_next("span")
            if isinstance(value, Tag):
                return _collapse(value.get_text())
        return ""

    @classmethod
    def _item(cls, raw: dict[str, Any], locale: str) -> dict[str, str]:
        """Одна позиция чека под зафиксированными названиями колонок."""
        item: dict[str, str] = {}
        for key, label in labels.ITEM_FIELDS:
            value = raw.get(key)
            if value is None or value == "":
                continue
            item[label.of(locale)] = (
                _number(value) if key in labels.ITEM_NUMERIC_KEYS else _collapse(str(value))
            )

        rate = cls._rate(raw)
        if rate:
            item[labels.ITEM_RATE.of(locale)] = rate
        return item

    @staticmethod
    def _rate(raw: dict[str, Any]) -> str:
        """Ставка налога: буква и процент одной строкой («Ђ (20%)»).

        Собирается из двух полей ответа: отдельной колонки под процент на
        странице нет, а терять его вместе с буквой незачем — буква без ставки
        не говорит ничего.
        """
        label = _collapse(str(raw.get("label") or ""))
        percent = raw.get("labelRate")
        if percent is None:
            return label
        return f"{label} ({_number(percent)}%)".lstrip()

    @staticmethod
    def _journal(page: BeautifulSoup) -> str:
        """Текст фискального журнала.

        Картинки из него удаляются до извлечения текста: внутри журнала лежит
        base64-GIF с QR-кодом на сорок килобайт, и он уехал бы и в JSONB, и в
        ячейку листа-архива, вытеснив оттуда сам чек.

        Журнал печатает ПФР, и он кириллический в обеих версиях страницы. Мы
        всё равно кладём его в обе: версия обязана быть самодостаточной, иначе
        читающему английскую придётся лезть в соседнюю за половиной чека.
        """
        journal = page.find("pre")
        if not isinstance(journal, Tag):
            return ""
        for image in journal.find_all("img"):
            image.decompose()
        return journal.get_text().strip()


def _collapse(value: str) -> str:
    """Схлопывает переводы строк и отступы разметки в одиночные пробелы."""
    return " ".join(value.split())


def _decimal_point(value: str) -> str:
    """Денежная строка со страницы в канонической точечной записи.

    Сербская страница печатает «610,38», английская — «610.38». Оставить как
    есть значило бы положить в JSON значение, которое `Decimal` не разберёт
    вовсе, и разбор сербской версии падал бы на итоге каждого чека. Разделителя
    разрядов на этих суммах сайт не ставит, поэтому запятая здесь всегда
    десятичная.
    """
    return value.replace(",", ".")


def _number(value: Any) -> str:
    """Число из ответа сервиса строкой, без `float` по пути.

    `str(value)` напрямую нельзя: `json` разбирает `0.584` в `float`, и на
    неудачном значении его строковое представление окажется
    «0.5840000000000001». `Decimal(str(...))` даёт ровно те цифры, что стояли в
    ответе.
    """
    try:
        return str(Decimal(str(value)))
    except InvalidOperation:
        return _collapse(str(value))
