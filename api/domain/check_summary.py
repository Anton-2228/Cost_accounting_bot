"""Сводка чека для уведомления: сумма, валюта, день покупки."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from api.enums import Currency


class CheckNotice(BaseModel):
    """Что `checks_service` сообщает о чеке для уведомления пользователю.

    Сумма и время покупки — из QR-строки: api форматов не знает и из сырья их
    не достаёт.
    """

    model_config = ConfigDict(frozen=True)

    total: Decimal
    purchased_at: datetime


class CheckSummary(BaseModel):
    """По чему пользователь узнает чек в уведомлении.

    Сумму и время покупки api из сырья не достаёт — форматов он не знает. Их
    присылает `checks_service`, который разобрал QR-строку, и живут они только
    в тексте уведомления.
    """

    model_config = ConfigDict(frozen=True)

    total: Decimal
    currency: Currency
    day: date

    @classmethod
    def of(cls, notice: CheckNotice, *, currency: Currency, timezone: str) -> CheckSummary:
        """Сводка для документа: день покупки — по часовому поясу документа.

        Время покупки с поясом (сербский чек приходит в UTC) переводится в пояс
        документа, иначе покупка после полуночи по местному времени попала бы в
        уведомление вчерашним днём. Время без пояса — уже местное.
        """
        moment = notice.purchased_at
        if moment.tzinfo is not None:
            moment = moment.astimezone(ZoneInfo(timezone))
        return cls(total=notice.total, currency=currency, day=moment.date())

    def params(self) -> dict[str, str | int]:
        """Параметры уведомления: данные, а не их представление."""
        return {
            "total": str(self.total),
            "currency": self.currency.value,
            "day": self.day.isoformat(),
        }
