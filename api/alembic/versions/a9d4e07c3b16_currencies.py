"""currencies for sources and records, exchange rate cache

Revision ID: a9d4e07c3b16
Revises: b6e2c04f7a18
Create Date: 2026-08-27 12:00:00.000000

До сих пор весь учёт был неявно рублёвым: суммы лежали числом без единицы, а
рубль жил в форматтере бота как символ «₽». Пока валюта одна, это работает и
незаметно; как только счетов становится два в разных валютах, `SUM(amount)`
складывает динары с евро и выдаёт число, не означающее ничего.

Валюта появляется в двух местах, и это **разные** валюты.

`sources.currency` — валюта, в которой ведётся счёт. В ней задан
`start_balance`, в ней же выражен вычисленный остаток.

`records.currency` — валюта конкретной операции, не обязательно совпадающая с
валютой счёта: динарами можно расплатиться с еврового счёта. Хранится
**исходная** сумма и её собственная валюта, а не приведённая к счёту. Записать
сюда результат конвертации значило бы похоронить настоящую сумму покупки: курс
известен только на день операции, и обратно из округлённых до копеек евро
динары уже не достать.

Дефолта у обеих колонок нет. `server_default` здесь ставится и тут же
снимается — он нужен ровно на время `ADD COLUMN NOT NULL`, чтобы существующие
строки получили значение. Оставить его насовсем значило бы завести «валюту по
умолчанию», которая молча подставится вместо опечатки в листе `Bills`, тогда
как импорт обязан такую строку отвергнуть. Выбран `RUB`: всё, что накоплено до
этой миграции, вводилось в рублях.

`transfers` не меняется. Сумма перевода по определению выражена в валюте
счёта-источника — это единственная валюта, которую пользователь называет, — а
зачисление считается по курсу. Вторая колонка суммы понадобилась бы, только
чтобы учитывать банковскую комиссию, и это отдельный разговор.

`exchange_rates` — кэш курсов, а не справочник. Строки появляются по
требованию, когда подсчёту впервые понадобился курс, которого ещё нет, и
больше не меняются: курс за прошедший день это факт, и перезапись означала бы,
что вчерашний остаток счёта сегодня стал другим. Таблица общая для всех
документов — курс евро к динару не зависит от того, чей учёт его спросил, — и
не знает мягкого удаления: удалять факт незачем, а `deleted_at` в уникальном
ключе означал бы, что у одного дня бывает два разных курса.

Курса валюты к себе самой в таблице нет, и `CHECK` это запрещает. Он всегда
единица; строки, единственная роль которых — когда-нибудь оказаться не
единицей, не нужны. В запросах единица подставляется через `CASE`.

Точность `NUMERIC(24, 12)` своя, не денежная: курс RSD→EUR это 0.0085, и два
знака после запятой округлили бы каждую динарную операцию в ноль — та же
причина, по которой `llm_usages.cost` не `NUMERIC(14, 2)`.

Откат обратный и теряет только кэш: курсы выкачиваются заново. Колонки валют
исчезают вместе с информацией о том, в чём именно была операция, — в старой
схеме она невыразима. `DROP TYPE` стоит последним: пока на тип ссылается хоть
одна колонка, удалить его нельзя.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d4e07c3b16"
down_revision: str | None = "b6e2c04f7a18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Тип объявлен модульно и с create_type=False по той же причине, что и в
# b1e6a4c7d905: инлайновый sa.Enum внутри add_column/create_table пытается
# выполнить CREATE TYPE сам, и делает это столько раз, сколько колонок его
# используют.
CURRENCY = postgresql.ENUM("RUB", "USD", "EUR", "RSD", name="currency", create_type=False)

#: Валюта, в которой вёлся учёт до появления этой миграции.
_LEGACY_CURRENCY = sa.text("'RUB'")

_CURRENCY_TABLES = ("sources", "records")


def upgrade() -> None:
    CURRENCY.create(op.get_bind(), checkfirst=True)

    for table in _CURRENCY_TABLES:
        # Дефолт живёт ровно один оператор: он нужен, чтобы существующие строки
        # получили значение при ADD COLUMN NOT NULL, и вреден дальше — см.
        # докстринг.
        op.add_column(
            table,
            sa.Column("currency", CURRENCY, nullable=False, server_default=_LEGACY_CURRENCY),
        )
        op.alter_column(table, "currency", server_default=None)

    op.create_table(
        "exchange_rates",
        sa.Column("base_currency", CURRENCY, nullable=False),
        sa.Column("quote_currency", CURRENCY, nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(precision=24, scale=12), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rate > 0", name=op.f("ck_exchange_rates_rate_positive")),
        sa.CheckConstraint(
            "base_currency <> quote_currency",
            name=op.f("ck_exchange_rates_currencies_differ"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exchange_rates")),
        # Ключ кэша и единственный способ его читать: агрегаты ищут строку ровно
        # по этой тройке, отдельный индекс был бы его копией.
        sa.UniqueConstraint(
            "base_currency",
            "quote_currency",
            "rate_date",
            name="uq_exchange_rates_pair_date",
        ),
    )


def downgrade() -> None:
    op.drop_table("exchange_rates")
    for table in _CURRENCY_TABLES:
        op.drop_column(table, "currency")
    # Строго последним: пока на тип ссылается колонка, удалить его нельзя.
    CURRENCY.drop(op.get_bind(), checkfirst=True)
