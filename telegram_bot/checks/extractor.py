"""Извлечение позиций из сырья чека.

Чистая функция «чек → позиции»: ни сети, ни aiogram, ни состояния — поэтому её
и покрывает таблица примеров. Api сырьё не интерпретирует вовсе: форматов чеков
больше одного, и решать, чью сумму считать настоящей, можно только здесь, зная
формат.

Разборщик на формат, выбор — по `check.kind`. Общего у них ровно три правила,
и каждое оплачено ошибкой старой версии:

* **ни одного `float` по пути.** У ФНС суммы приходят копейками, и перевод
  делается только `Decimal(копейки) / 100`; у сербского — строками, и они
  превращаются в `Decimal` напрямую. `product["sum"] / 100` давал `float`;
* **итог сверяется.** Сумма позиций сравнивается с итогом чека. Это канарейка
  на «прочитали не то поле»: если бы разбор взял цену вместо суммы или
  пропустил позицию, расхождение вылезло бы сразу, а не расхождением в отчёте
  через месяц;
* **отсутствие поля — внятная ошибка**, а не `KeyError` мимо обработчика.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import parse_qsl

from telegram_bot import constants
from telegram_bot.api_client.models import Check, CheckKind
from telegram_bot.checks import srb_labels
from telegram_bot.checks.errors import (
    ReceiptFormatError,
    ReceiptMismatchError,
    ReceiptNotSupportedError,
)
from telegram_bot.checks.models import Receipt, ReceiptItem, currency_of
from telegram_bot.i18n import LocaleFormat, t

#: Поля расшифровки ФНС, в которых может лежать название магазина, в порядке
#: убывания внятности: «Пятёрочка» лучше, чем «ООО ТД Перекрёсток», а адрес —
#: лучше, чем ничего.
_PLACE_FIELDS = ("retailPlace", "user", "retailPlaceAddress")


def _manual(key: str, **params: object) -> str:
    """Отказ с общим хвостом «внесите вручную, а чек уберите».

    Хвост — отдельной строкой каталога, а не частью каждого отказа: что делать
    пользователю, когда чек не разобрать, одно и то же, и формулировать это в
    каждом из десятка отказов значило бы переводить одно и то же десять раз.
    """
    return f"{t(key, **params)}\n{t('receipt.manual_tail')}"


def _remove(key: str, **params: object) -> str:
    """Отказ с хвостом «уберите чек из очереди»."""
    return f"{t(key, **params)}\n{t('receipt.remove_tail')}"


def _money(value: Decimal) -> str:
    """Сумма для текста отказа — с разделением разрядов по языку."""
    return LocaleFormat.decimal(value, constants.MONEY_DECIMAL_PLACES)


class _FormatExtractor(Protocol):
    """Разборщик сырья одного формата."""

    @classmethod
    def extract(cls, check: Check) -> Receipt:
        """Собирает :class:`Receipt` из сырья чека."""
        ...


class RuFnsExtractor:
    """Достаёт позиции и шапку из ответа proverkacheka.com."""

    @classmethod
    def extract(cls, check: Check) -> Receipt:
        """Собирает :class:`Receipt` из сырья чека ФНС.

        `check.qr_raw` нужен как запасной источник итога и времени покупки: в
        расшифровке этих полей может не быть, а в QR-строке они есть всегда —
        по ним чек и находили.
        """
        body = cls._body(check.raw_payload)
        cls._assert_purchase(body)

        items = cls._items(body)
        total_kopecks = cls._total_kopecks(body, check.qr_raw)
        cls._assert_total_matches(items, total_kopecks)

        return Receipt(
            items=[
                ReceiptItem(name=name, amount=_to_rubles(kopecks)) for name, kopecks in items
            ],
            total=_to_rubles(total_kopecks),
            currency=currency_of(check.kind),
            retail_place=cls._retail_place(body),
            purchased_at=cls._purchased_at(body, check.qr_raw),
        )

    @staticmethod
    def _body(raw_payload: dict[str, Any]) -> dict[str, Any]:
        """Содержимое чека внутри ответа внешнего сервиса."""
        data = raw_payload.get("data")
        body = data.get("json") if isinstance(data, dict) else None
        if not isinstance(body, dict):
            raise ReceiptFormatError(
                _manual("receipt.unexpected_shape")
            )
        return body

    @staticmethod
    def _assert_purchase(body: dict[str, Any]) -> None:
        """Отвергает всё, что не является обычной покупкой."""
        operation = body.get("operationType")
        if operation is not None and operation != constants.RECEIPT_OPERATION_INCOME:
            raise ReceiptNotSupportedError(
                _remove("receipt.refund")
            )

    @classmethod
    def _items(cls, body: dict[str, Any]) -> list[tuple[str, int]]:
        """Позиции чека парами «название, сумма в копейках»."""
        raw_items = body.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ReceiptFormatError(
                _manual("receipt.no_items")
            )

        items: list[tuple[str, int]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ReceiptFormatError(
                    _remove("receipt.items_shape")
                )
            items.append((_name(raw_item.get("name")), cls._kopecks(raw_item.get("sum"))))
        return items

    @staticmethod
    def _kopecks(value: Any) -> int:
        """Сумма позиции в копейках.

        Дробное значение здесь означает, что сервис отдал рубли там, где мы
        ждём копейки, — то есть разбор смотрит не в то поле. Молча округлить
        значило бы записать сумму в сто раз меньше настоящей.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise ReceiptFormatError(
                _remove("receipt.not_kopecks")
            )
        if value < 0:
            raise ReceiptNotSupportedError(
                _remove("receipt.negative_item")
            )
        return value

    @classmethod
    def _total_kopecks(cls, body: dict[str, Any], qr_raw: str) -> int:
        """Итог чека в копейках: из расшифровки, иначе из QR-строки."""
        total = body.get("totalSum")
        if isinstance(total, int) and not isinstance(total, bool):
            return total

        from_qr = _qr_field(qr_raw, "s")
        if from_qr is not None:
            try:
                return int(Decimal(from_qr.replace(",", ".")) * constants.KOPECKS_IN_RUBLE)
            except (InvalidOperation, ValueError):
                pass

        raise ReceiptFormatError(
            _manual("receipt.no_total")
        )

    @staticmethod
    def _assert_total_matches(items: list[tuple[str, int]], total_kopecks: int) -> None:
        """Сверяет сумму позиций с итогом чека.

        Сравнение целочисленное, в копейках: обе величины приходят такими, и
        приводить их к рублям ради сравнения значило бы завести округление там,
        где его можно не заводить.
        """
        items_total = sum(kopecks for _, kopecks in items)
        if items_total != total_kopecks:
            raise ReceiptMismatchError(
                t(
                    "receipt.mismatch",
                    items=_money(_to_rubles(items_total)),
                    total=_money(_to_rubles(total_kopecks)),
                )
            )

    @staticmethod
    def _retail_place(body: dict[str, Any]) -> str:
        """Название магазина, если оно вообще есть в расшифровке."""
        for field in _PLACE_FIELDS:
            value = body.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _purchased_at(body: dict[str, Any], qr_raw: str) -> datetime | None:
        """Момент покупки из расшифровки, иначе из QR-строки.

        Часовой пояс не приписывается: это местное время кассы, и показывается
        оно только пользователю. Дата операции берётся не отсюда — её ставит api
        по часовому поясу документа в день разбора.
        """
        raw = body.get("dateTime")
        if isinstance(raw, str):
            parsed = _parse_iso(raw)
            if parsed is not None:
                return parsed
        elif isinstance(raw, int) and not isinstance(raw, bool):
            return datetime.fromtimestamp(raw)  # noqa: DTZ006 — местное время кассы

        moment = _qr_field(qr_raw, "t")
        if moment is None:
            return None
        for pattern in constants.RECEIPT_DATETIME_FORMATS:
            try:
                return datetime.strptime(moment, pattern)  # noqa: DTZ007
            except ValueError:
                continue
        return None


class SrbSufExtractor:
    """Достаёт позиции и шапку из расшифровки сербского чека.

    Читает сербскую языковую версию, а не английскую: подписи в ней стоят
    ближе к бумажке, и версия эта есть у любого чека. Английская хранится для
    человека, а не для разбора.

    Суммы приходят строками — приём приводит их к строкам осознанно, чтобы не
    заводить `float` в JSONB, — и превращаются в `Decimal` напрямую, без
    промежуточного числа с плавающей точкой.
    """

    @classmethod
    def extract(cls, check: Check) -> Receipt:
        """Собирает :class:`Receipt` из сырья сербского чека."""
        body = cls._body(check.raw_payload)
        cls._assert_purchase(body)

        items = cls._items(body)
        total = cls._total(body)
        cls._assert_total_matches(items, total)

        return Receipt(
            items=[ReceiptItem(name=name, amount=amount) for name, amount in items],
            total=total,
            currency=currency_of(check.kind),
            retail_place=cls._retail_place(body),
            purchased_at=cls._purchased_at(body),
        )

    @staticmethod
    def _body(raw_payload: dict[str, Any]) -> dict[str, Any]:
        """Сербская языковая версия чека."""
        body = raw_payload.get(srb_labels.VERSION)
        if not isinstance(body, dict):
            raise ReceiptFormatError(
                _manual("receipt.unexpected_shape")
            )
        return body

    @staticmethod
    def _assert_purchase(body: dict[str, Any]) -> None:
        """Отвергает всё, что не является обычной продажей.

        Отсутствие поля пропускается: вид чека печатает страница, и её молчание
        не повод отказать в разборе — итог всё равно будет сверен.
        """
        invoice_type = body.get(srb_labels.INVOICE_TYPE)
        if invoice_type is not None and invoice_type != srb_labels.INVOICE_TYPE_NORMAL:
            raise ReceiptNotSupportedError(
                _remove("receipt.not_sale", invoice_type=invoice_type)
            )

    @classmethod
    def _items(cls, body: dict[str, Any]) -> list[tuple[str, Decimal]]:
        """Позиции чека парами «название, сумма в динарах»."""
        raw_items = body.get(srb_labels.SPECIFICATION)
        if not isinstance(raw_items, list) or not raw_items:
            raise ReceiptFormatError(
                _manual("receipt.no_items")
            )

        items: list[tuple[str, Decimal]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ReceiptFormatError(
                    _remove("receipt.items_shape")
                )
            amount = cls._amount(raw_item.get(srb_labels.ITEM_TOTAL))
            if amount < 0:
                raise ReceiptNotSupportedError(
                    _remove("receipt.negative_item")
                )
            items.append((_name(raw_item.get(srb_labels.ITEM_NAME)), amount))
        return items

    @staticmethod
    def _amount(value: Any) -> Decimal:
        """Сумма из расшифровки.

        `str(value)` перед `Decimal` намеренно: приём кладёт суммы строками, но
        чек мог быть сохранён и до этого правила, и `Decimal(float)` дал бы
        двоичный хвост вместо записанных цифр.
        """
        try:
            return Decimal(str(value))
        except InvalidOperation as error:
            raise ReceiptFormatError(
                _remove("receipt.not_numbers")
            ) from error

    @classmethod
    def _total(cls, body: dict[str, Any]) -> Decimal:
        """Итог чека."""
        total = body.get(srb_labels.TOTAL_AMOUNT)
        if total is None:
            raise ReceiptFormatError(
                _manual("receipt.no_total")
            )
        return cls._amount(total)

    @staticmethod
    def _assert_total_matches(items: list[tuple[str, Decimal]], total: Decimal) -> None:
        """Сверяет сумму позиций с итогом чека.

        Сравнение точное, без допуска: обе величины приходят десятичными и с
        одинаковым числом знаков, и допуск здесь означал бы согласие тихо
        записать не ту сумму.
        """
        items_total = sum((amount for _, amount in items), start=Decimal("0"))
        if items_total != total:
            raise ReceiptMismatchError(
                t("receipt.mismatch", items=_money(items_total), total=_money(total))
            )

    @staticmethod
    def _retail_place(body: dict[str, Any]) -> str:
        """Название магазина, иначе юрлица.

        Магазин точнее: «195 - Maxi» говорит покупателю больше, чем
        «DELHAIZE SERBIA DOO BEOGRAD», под которым работает и он, и ещё сотни.
        """
        for field in (srb_labels.SHOP_FULL_NAME, srb_labels.COMPANY):
            value = body.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _purchased_at(body: dict[str, Any]) -> datetime | None:
        """Момент выдачи чека, как его напечатала страница.

        Часовой пояс не приписывается: страница подписывает это время «зона
        сервера», и показывается оно только пользователю.
        """
        raw = body.get(srb_labels.SDC_DATE_TIME)
        if not isinstance(raw, str):
            return None
        try:
            return datetime.strptime(raw.strip(), srb_labels.DATETIME_FORMAT)  # noqa: DTZ007
        except ValueError:
            return None


#: Разборщик на формат. Формат без разборщика — ошибка сборки, а не входных
#: данных: приём не умеет сохранить чек, вида которого не знает.
_EXTRACTORS: dict[CheckKind, type[_FormatExtractor]] = {
    CheckKind.RU_FNS: RuFnsExtractor,
    CheckKind.SRB_SUF: SrbSufExtractor,
}


class ReceiptExtractor:
    """Выбирает разборщик по виду чека."""

    @staticmethod
    def extract(check: Check) -> Receipt:
        """Собирает :class:`Receipt` из сырья чека любого известного формата."""
        extractor = _EXTRACTORS.get(check.kind)
        if extractor is None:
            raise ReceiptFormatError(
                _manual("receipt.unknown_format")
            )
        return extractor.extract(check)


def _name(raw_name: Any) -> str:
    """Название позиции, обрезанное до серверного предела.

    Позиция без названия получает заглушку на языке обращения. Заглушка — уже
    данные: она уходит в `records.product_name` и становится ключом кэша типов,
    так что после смены языка у безымянных позиций заведётся своя запись на
    каждом языке. Это принято: смесь языков в таблице после смены допустима.
    """
    name = str(raw_name).strip() if raw_name is not None else ""
    return (name or t("receipt.unnamed_product"))[: constants.PRODUCT_NAME_MAX_LENGTH]


def _to_rubles(kopecks: int) -> Decimal:
    """Копейки в рубли. Только `Decimal`, ни одного `float` по пути."""
    return Decimal(kopecks) / constants.KOPECKS_IN_RUBLE


def _parse_iso(raw: str) -> datetime | None:
    """Разбирает строку даты из расшифровки, не падая на чужом формате."""
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _qr_field(qr_raw: str, name: str) -> str | None:
    """Значение поля QR-строки или `None`."""
    if not qr_raw:
        return None
    value = dict(parse_qsl(qr_raw.strip(), keep_blank_values=True)).get(name)
    return value or None
