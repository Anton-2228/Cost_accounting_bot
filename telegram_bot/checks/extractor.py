"""Извлечение позиций из сырья чека.

Чистая функция «`raw_payload` → позиции»: ни сети, ни aiogram, ни состояния —
поэтому её и покрывает таблица примеров. Api сырьё не интерпретирует вовсе:
форматов чеков будет больше одного, и решать, чью сумму считать настоящей,
можно только здесь, зная формат.

Три правила, каждое из которых оплачено ошибкой старой версии:

* **суммы — копейки**, и перевод в рубли делается один раз и только
  `Decimal(копейки) / 100`. `product["sum"] / 100` давал `float`;
* **итог сверяется**. Сумма позиций сравнивается с `totalSum` целочисленно, в
  копейках. Это канарейка на «прочитали не то поле»: если бы разбор взял `price`
  вместо `sum` или пропустил позицию, расхождение вылезло бы сразу, а не
  расхождением в отчёте через месяц;
* **отсутствие поля — внятная ошибка**, а не `KeyError` мимо обработчика.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl

from telegram_bot import constants
from telegram_bot.checks.errors import (
    ReceiptFormatError,
    ReceiptMismatchError,
    ReceiptNotSupportedError,
)
from telegram_bot.checks.models import Receipt, ReceiptItem

#: Поля расшифровки, в которых может лежать название магазина, в порядке
#: убывания внятности: «Пятёрочка» лучше, чем «ООО ТД Перекрёсток», а адрес —
#: лучше, чем ничего.
_PLACE_FIELDS = ("retailPlace", "user", "retailPlaceAddress")


class ReceiptExtractor:
    """Достаёт позиции и шапку из ответа внешнего сервиса расшифровки."""

    @classmethod
    def extract(cls, raw_payload: dict[str, Any], qr_raw: str = "") -> Receipt:
        """Собирает :class:`Receipt` из сырья чека ФНС.

        `qr_raw` нужен как запасной источник итога и времени покупки: в
        расшифровке этих полей может не быть, а в QR-строке они есть всегда —
        по ним чек и находили.
        """
        body = cls._body(raw_payload)
        cls._assert_purchase(body)

        items = cls._items(body)
        total_kopecks = cls._total_kopecks(body, qr_raw)
        cls._assert_total_matches(items, total_kopecks)

        return Receipt(
            items=[
                ReceiptItem(name=name, amount=_to_rubles(kopecks)) for name, kopecks in items
            ],
            total=_to_rubles(total_kopecks),
            retail_place=cls._retail_place(body),
            purchased_at=cls._purchased_at(body, qr_raw),
        )

    @staticmethod
    def _body(raw_payload: dict[str, Any]) -> dict[str, Any]:
        """Содержимое чека внутри ответа внешнего сервиса."""
        data = raw_payload.get("data")
        body = data.get("json") if isinstance(data, dict) else None
        if not isinstance(body, dict):
            raise ReceiptFormatError(
                "Расшифровка этого чека неожиданной формы — разобрать её не могу.\n"
                "Внесите покупки вручную через /add, а чек уберите: /check_del"
            )
        return body

    @staticmethod
    def _assert_purchase(body: dict[str, Any]) -> None:
        """Отвергает всё, что не является обычной покупкой."""
        operation = body.get("operationType")
        if operation is not None and operation != constants.RECEIPT_OPERATION_INCOME:
            raise ReceiptNotSupportedError(
                "Чеки-возвраты пока не поддерживаются, внесите операцию вручную.\n"
                "Убрать чек из очереди: /check_del"
            )

    @classmethod
    def _items(cls, body: dict[str, Any]) -> list[tuple[str, int]]:
        """Позиции чека парами «название, сумма в копейках»."""
        raw_items = body.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ReceiptFormatError(
                "В расшифровке чека нет ни одной позиции — разбирать нечего.\n"
                "Внесите покупки вручную через /add, а чек уберите: /check_del"
            )

        items: list[tuple[str, int]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ReceiptFormatError(
                    "Позиции чека записаны не так, как ожидалось — разобрать не могу.\n"
                    "Убрать чек из очереди: /check_del"
                )
            items.append((cls._name(raw_item), cls._kopecks(raw_item.get("sum"))))
        return items

    @staticmethod
    def _name(raw_item: dict[str, Any]) -> str:
        """Название позиции, обрезанное до серверного предела."""
        raw_name = raw_item.get("name")
        name = str(raw_name).strip() if raw_name is not None else ""
        return (name or constants.UNNAMED_PRODUCT)[: constants.PRODUCT_NAME_MAX_LENGTH]

    @staticmethod
    def _kopecks(value: Any) -> int:
        """Сумма позиции в копейках.

        Дробное значение здесь означает, что сервис отдал рубли там, где мы
        ждём копейки, — то есть разбор смотрит не в то поле. Молча округлить
        значило бы записать сумму в сто раз меньше настоящей.
        """
        if isinstance(value, bool) or not isinstance(value, int):
            raise ReceiptFormatError(
                "Суммы в расшифровке чека записаны не в копейках — разобрать не могу.\n"
                "Убрать чек из очереди: /check_del"
            )
        if value < 0:
            raise ReceiptNotSupportedError(
                "В чеке есть позиция с отрицательной суммой — внесите её вручную.\n"
                "Убрать чек из очереди: /check_del"
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
            "В чеке не нашлось итоговой суммы, сверить позиции не с чем.\n"
            "Внесите покупки вручную через /add, а чек уберите: /check_del"
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
                "Сумма позиций не сошлась с итогом чека: "
                f"{_to_rubles(items_total)} против {_to_rubles(total_kopecks)}.\n"
                "Записывать такой чек не буду — внесите покупки вручную через /add"
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
