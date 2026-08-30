"""ORM-модель кэша курсов валют."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import CURRENCY, RATE
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import Currency


class ExchangeRateORM(PkMixin, TimestampMixin, Base):
    """Курс `base_currency` → `quote_currency` на дату `rate_date`.

    Кэш, а не справочник: строки появляются по требованию, когда подсчёту
    остатка или статистики впервые понадобился курс, которого ещё нет. Раз
    появившись, строка не меняется — курс за прошедший день это факт, и
    перезапись означала бы, что вчерашний остаток счёта сегодня стал другим.
    Поэтому запись идёт через `ON CONFLICT DO NOTHING`, а не `DO UPDATE`.

    Таблица **общая для всех документов**: курс евро к динару не зависит от
    того, чей учёт его спросил. Колонки `spreadsheet_id` здесь нет намеренно —
    иначе один и тот же день выкачивался бы заново для каждого пользователя.

    Мягкого удаления нет по той же причине: удалять факт не за чем, а
    `deleted_at` в уникальном ключе означал бы, что один день может иметь два
    разных курса.

    `base_currency <> quote_currency` — курс валюты к себе самой всегда единица.
    Хранить её значило бы завести строки, единственная роль которых —
    когда-нибудь оказаться не единицей. В запросах она подставляется через
    `CASE`.
    """

    __tablename__ = "exchange_rates"
    __table_args__ = (
        # Ключ кэша. Он же единственный способ его читать: агрегаты ищут строку
        # ровно по этой тройке, отдельный индекс был бы его копией.
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "rate_date",
            name="uq_exchange_rates_pair_date",
        ),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base_currency <> quote_currency", name="currencies_differ"),
    )

    base_currency: Mapped[Currency] = mapped_column(CURRENCY, nullable=False)
    quote_currency: Mapped[Currency] = mapped_column(CURRENCY, nullable=False)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
