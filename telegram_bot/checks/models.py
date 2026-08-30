"""Результат извлечения позиций из сырья чека."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from telegram_bot.api_client.models import Currency

#: Валюта чека ФНС. Формат физически рублёвый — суммы в нём и приходят
#: целыми копейками, — поэтому это свойство формата, а не выбор
#: пользователя. Зеркало `_CHECK_CURRENCY` в `api.services.check_service`,
#: где по этой же причине валюта проставляется операциям чека.
CHECK_CURRENCY = Currency.RUB


class ReceiptItem(BaseModel):
    """Одна позиция чека: название и сумма в рублях.

    Сумма уже `Decimal` и уже в рублях. Перевод из копеек делается ровно один
    раз, в извлечении, и только делением `Decimal`: старая версия писала
    `product["sum"] / 100` и получала `float`, нарушая инвариант «деньги —
    `Decimal`» в самой первой точке пути.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    amount: Decimal


class Receipt(BaseModel):
    """Чек, разобранный до позиций и шапки.

    Шапка нужна пользователю, чтобы узнать бумажку в руках: магазин, время и
    итог. Ни одно из этих полей не едет в api — там чек уже лежит целиком.
    """

    model_config = ConfigDict(frozen=True)

    items: list[ReceiptItem]
    total: Decimal
    retail_place: str = ""
    purchased_at: datetime | None = None
