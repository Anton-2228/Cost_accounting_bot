"""Результат извлечения позиций из сырья чека."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from telegram_bot.api_client.models import CheckKind, Currency

#: Валюта чека по его формату. Не спрашивается у пользователя и не извлекается
#: из расшифровки: каждый формат привязан к своей стране и своей валюте. Чек
#: ФНС физически рублёвый — суммы в нём приходят целыми копейками; сербский так
#: же жёстко динарный. Зеркало `_CHECK_CURRENCY` в `api.services.check_service`,
#: где по этой же причине валюта проставляется операциям чека.
_CHECK_CURRENCY: dict[CheckKind, Currency] = {
    CheckKind.RU_FNS: Currency.RUB,
    CheckKind.SRB_SUF: Currency.RSD,
}


def currency_of(kind: CheckKind) -> Currency:
    """Валюта чека этого формата."""
    return _CHECK_CURRENCY[kind]


class ReceiptItem(BaseModel):
    """Одна позиция чека: название и сумма.

    Сумма уже `Decimal` и уже в основных единицах валюты. Перевод из копеек
    делается ровно один раз, в извлечении, и только делением `Decimal`: старая
    версия писала `product["sum"] / 100` и получала `float`, нарушая инвариант
    «деньги — `Decimal`» в самой первой точке пути.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    amount: Decimal


class Receipt(BaseModel):
    """Чек, разобранный до позиций и шапки.

    Шапка нужна пользователю, чтобы узнать бумажку в руках: магазин, время и
    итог. Ни одно из этих полей не едет в api — там чек уже лежит целиком.

    `currency` берётся из формата чека, а не из его расшифровки: api проставит
    операциям ровно ту же, и разойтись эти два решения не могут.
    """

    model_config = ConfigDict(frozen=True)

    items: list[ReceiptItem]
    total: Decimal
    currency: Currency
    retail_place: str = ""
    purchased_at: datetime | None = None
