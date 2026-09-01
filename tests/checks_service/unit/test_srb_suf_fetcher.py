"""Тесты сборки расшифровки сербского чека.

Страницы в фикстурах настоящие — снятые с `suf.purs.gov.rs`, без base64-картинок
и внешних ресурсов. Это существенно: разметка сайта содержит незакрытые теги,
и фикстура «как надо бы» проверяла бы разбор HTML, которого в жизни нет.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from checks_service import constants
from checks_service.exceptions import ReceiptFetchError, ReceiptNotFoundError
from checks_service.formats.srb_suf import labels
from checks_service.formats.srb_suf.fetcher import SufFetcher
from checks_service.formats.srb_suf.parser import SrbSufQrParser
from tests.checks_service.factories import (
    SRB_SUF_KEY,
    SRB_SUF_QR,
    SRB_SUF_TOKEN,
    suf_page,
    suf_specifications,
)

BASE_URL = "https://suf.purs.gov.rs"

Handler = Callable[[httpx.Request], httpx.Response]


def _handler(
    *,
    page_status: int = 200,
    specifications: str | None = None,
    specifications_status: int = 200,
) -> tuple[Handler, list[httpx.Request]]:
    """Поддельный сайт ПУРС и журнал обращений к нему.

    Журнал нужен затем, что у сборки почти нет наблюдаемого поведения помимо
    результата: «сходил за позициями дважды» или «не сходил за английской
    версией» видно только так.
    """
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == constants.SRB_SUF_SPECIFICATIONS_PATH:
            body = suf_specifications() if specifications is None else specifications
            return httpx.Response(specifications_status, text=body)
        if page_status != 200:
            return httpx.Response(page_status)
        locale = request.headers.get("cookie", "").split("=")[-1]
        return httpx.Response(200, text=suf_page(locale))

    return handle, seen


def _fetcher(handler: Handler) -> SufFetcher:
    """Фетчер поверх поддельного сайта."""
    return SufFetcher(BASE_URL, timeout=1.0, transport=httpx.MockTransport(handler))


async def _fetch(handler: Handler) -> dict[str, Any]:
    """Расшифровка чека из образца ссылки."""
    fetcher = _fetcher(handler)
    try:
        return await fetcher.fetch(SrbSufQrParser().parse(SRB_SUF_QR))
    finally:
        await fetcher.aclose()


async def test_both_language_versions_are_saved() -> None:
    """Сохраняются обе версии — сербская и английская — и сама ссылка.

    Ссылка нужна не для красоты: по ней чек открывается заново, и без неё
    расшифровка перестаёт быть проверяемой.
    """
    payload = await _fetch(_handler()[0])

    assert payload[labels.URL_FIELD] == SRB_SUF_QR
    assert payload[labels.INVOICE_NUMBER_FIELD] == SRB_SUF_KEY

    serbian = payload[labels.SR_FIELD]
    english = payload[labels.EN_FIELD]
    assert serbian["ПИБ"] == "103482850"
    assert english["TIN"] == "103482850"
    # Обе версии — точкой: сербская страница печатает «610,38», но запятая в
    # JSON это ловушка, `Decimal("610,38")` не разбирается вовсе.
    assert serbian["Укупан износ"] == "610.38"
    assert english["Total Amount"] == "610.38"
    # Вид операции — единственное поле шапки, которое сайт действительно
    # переводит, и ради него разбор и различает версии.
    assert serbian["Врста"] == "Промет"
    assert english["Type"] == "Normal"


async def test_versions_carry_the_same_fields_under_different_names() -> None:
    """Версии зеркальны: то же содержимое, но подписи на своём языке."""
    payload = await _fetch(_handler()[0])

    serbian = payload[labels.SR_FIELD]
    english = payload[labels.EN_FIELD]
    for element_id, label in labels.SPAN_FIELDS:
        assert (label.sr in serbian) == (label.en in english), element_id
    assert len(serbian[labels.SPECIFICATION.sr]) == len(english[labels.SPECIFICATION.en])


async def test_company_name_comes_from_the_print_block() -> None:
    """Название юрлица снимается из блока печати — больше его нигде нет.

    «1002342-195 - Maxi» не говорит, чей это чек; «DELHAIZE SERBIA DOO
    BEOGRAD» говорит.
    """
    payload = await _fetch(_handler()[0])

    assert payload[labels.SR_FIELD]["Предузеће"] == "DELHAIZE SERBIA DOO BEOGRAD"
    assert payload[labels.EN_FIELD]["Company"] == "DELHAIZE SERBIA DOO BEOGRAD"
    assert payload[labels.SR_FIELD]["ЕСИР број"] == "253/49.0"


async def test_items_are_fetched_once_and_placed_in_both_versions() -> None:
    """Позиции запрашиваются одним запросом: от языка они не зависят.

    Второй запрос был бы платой за ту же копию — и лишней нагрузкой на сайт
    налоговой, который нас об этом не просил.
    """
    handler, seen = _handler()
    payload = await _fetch(handler)

    specifications = [
        request
        for request in seen
        if request.url.path == constants.SRB_SUF_SPECIFICATIONS_PATH
    ]
    assert len(specifications) == 1
    assert b"invoiceNumber=YMQQWGKC-YMQQWGKC-81803" in specifications[0].content
    assert SRB_SUF_TOKEN.encode() in specifications[0].content

    serbian_items = payload[labels.SR_FIELD][labels.SPECIFICATION.sr]
    assert len(serbian_items) == 5
    assert serbian_items[0]["Назив"] == "Banana/KG"
    assert serbian_items[0]["Укупна цена"] == "93.43"
    assert serbian_items[0]["Количина"] == "0.584"
    assert serbian_items[0]["ГТИН"] == "28215580"
    # Ставка собирается из двух полей ответа: колонки под процент на странице
    # нет, а буква без него не говорит ничего.
    assert serbian_items[0]["Стопа"] == "Е (10%)"
    assert payload[labels.EN_FIELD][labels.SPECIFICATION.en][0]["Name"] == "Banana/KG"


async def test_only_money_is_normalised_to_a_decimal_point() -> None:
    """Запятая правится только у денег, у прочих полей — ни в коем случае.

    Догадка «всё, что похоже на число» испортила бы и ЕСИР номер «253/49.0», и
    ПИБ, и счётчики — молча и не сразу заметно.
    """
    serbian = (await _fetch(_handler()[0]))[labels.SR_FIELD]

    assert serbian["ЕСИР број"] == "253/49.0"
    assert serbian["ПИБ"] == "103482850"
    assert serbian["Бројач укупног броја"] == "81803"
    assert serbian["ПФР време (временска зона сервера)"] == "27.8.2026. 15:00:00"


async def test_pages_are_requested_in_both_locales() -> None:
    """За каждой версией ходим со своей кукой языка.

    Ни `Accept-Language`, ни параметр запроса на язык страницы не влияют —
    сайт смотрит только на куку.
    """
    handler, seen = _handler()
    await _fetch(handler)

    cookies = [
        request.headers.get("cookie", "")
        for request in seen
        if request.url.path != constants.SRB_SUF_SPECIFICATIONS_PATH
    ]
    assert cookies == [
        f"{constants.SRB_SUF_LOCALE_COOKIE}={constants.SRB_SUF_LOCALE_SR}",
        f"{constants.SRB_SUF_LOCALE_COOKIE}={constants.SRB_SUF_LOCALE_EN}",
    ]


async def test_no_float_anywhere_in_the_payload() -> None:
    """Ни одного числа с плавающей точкой во всём JSON.

    Сервис отдаёт `0.584` и `93.43` числами, но деньги во всей системе
    десятичные, и `float` в JSONB стал бы источником расхождений там, где их
    неоткуда взять.
    """
    payload = await _fetch(_handler()[0])

    floats: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, float):
            floats.append(node)

    walk(payload)
    assert floats == []
    # И сериализуется без сюрпризов: JSONB получит ровно это.
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


async def test_journal_is_kept_without_its_embedded_image() -> None:
    """Журнал сохраняется, картинка QR из него — нет.

    Внутри журнала лежит base64-GIF на сорок килобайт: он вытеснил бы сам чек
    из ячейки листа-архива.
    """
    payload = await _fetch(_handler()[0])

    journal = payload[labels.SR_FIELD][labels.JOURNAL.sr]
    assert "ФИСКАЛНИ РАЧУН" in journal
    assert "Укупан износ:" in journal
    assert "base64" not in journal
    # Журнал печатает ПФР, и он кириллический в обеих версиях. Версия обязана
    # быть самодостаточной: иначе за половиной чека придётся лезть в соседнюю.
    assert payload[labels.EN_FIELD][labels.JOURNAL.en] == journal


async def test_missing_receipt_is_told_apart_from_a_failure() -> None:
    """400 — «такого чека нет»: повтор даст тот же ответ, и врать нельзя."""
    handler, _ = _handler(page_status=400)
    with pytest.raises(ReceiptNotFoundError):
        await _fetch(handler)


async def test_server_error_is_a_failure_not_a_missing_receipt() -> None:
    """500 — сбой сервиса: тут повтор как раз имеет смысл."""
    handler, _ = _handler(page_status=503)
    with pytest.raises(ReceiptFetchError) as failure:
        await _fetch(handler)
    assert not isinstance(failure.value, ReceiptNotFoundError)


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ('{"success":false}', 200),
        ("не json вовсе", 200),
        ('{"success":true,"items":"нет"}', 200),
        ('{"success":true,"items":[]}', 500),
    ],
    ids=["отказ", "не JSON", "чужая структура", "ошибка сервиса"],
)
async def test_nothing_is_returned_when_items_are_unavailable(body: str, status: int) -> None:
    """Без позиций чек не собирается вовсе.

    Половина чека хуже отсутствующего: разбору пришлось бы уметь работать с
    получеками, а пользователю — догадываться, почему в чеке нет покупок.
    """
    handler, _ = _handler(specifications=body, specifications_status=status)
    with pytest.raises(ReceiptFetchError):
        await _fetch(handler)


async def test_values_are_collapsed_to_one_line() -> None:
    """Отступы разметки не уезжают в значения.

    Страница кладёт значение на отдельной строке с отступом в тридцать
    пробелов; без схлопывания в JSON приехал бы этот отступ.
    """
    payload = await _fetch(_handler()[0])

    for value in payload[labels.SR_FIELD].values():
        if isinstance(value, str) and value != payload[labels.SR_FIELD].get("Журнал"):
            assert value == value.strip()
            assert "\n" not in value
