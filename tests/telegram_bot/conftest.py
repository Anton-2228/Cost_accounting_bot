"""Фикстуры тестов бота.

Настройки бота читаются на импорте `telegram_bot.config`, поэтому переменные
окружения выставляются здесь — до первого импорта `telegram_bot.*`. Тот же
приём, что в корневом `conftest.py` для api, и по той же причине.

Сети и Redis эти тесты не касаются: предмет проверки — чистая логика разбора
ввода, подбора по псевдонимам, форматирования и перевода ошибок в русский
текст.
"""

from __future__ import annotations

import os
from decimal import Decimal

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:AAHtesttesttesttesttesttesttesttest")
os.environ.setdefault("API_BASE_URL", "http://api:8000/api/v1")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "")

import pytest  # noqa: E402

from telegram_bot.api_client.models import (  # noqa: E402
    Category,
    CategoryKind,
    EntityStatus,
    Source,
)


def make_category(
    *,
    category_id: int = 1,
    title: str = "Продукты",
    kind: CategoryKind = CategoryKind.EXPENSE,
    associations: list[str] | None = None,
) -> Category:
    """Категория для тестов.

    Псевдонимы уже в нижнем регистре: api хранит их нормализованными, и
    `CHECK alias = lower(alias)` не пропустит других.
    """
    return Category(
        id=category_id,
        kind=kind,
        status=EntityStatus.ACTIVE,
        title=title,
        associations=associations if associations is not None else [title.lower()],
        product_types=[],
    )


def make_source(
    *,
    source_id: int = 1,
    title: str = "Карта",
    associations: list[str] | None = None,
) -> Source:
    """Счёт для тестов."""
    return Source(
        id=source_id,
        status=EntityStatus.ACTIVE,
        title=title,
        associations=associations if associations is not None else [title.lower()],
        start_balance=Decimal("0.00"),
    )


@pytest.fixture
def categories() -> list[Category]:
    """Пара категорий: расход и доход."""
    return [
        make_category(category_id=1, title="Продукты", associations=["продукты", "еда"]),
        make_category(
            category_id=2,
            title="Зарплата",
            kind=CategoryKind.INCOME,
            associations=["зарплата", "зп"],
        ),
    ]


@pytest.fixture
def sources() -> list[Source]:
    """Пара счетов."""
    return [
        make_source(source_id=1, title="Карта", associations=["карта"]),
        make_source(source_id=2, title="Наличные", associations=["наличные", "нал"]),
    ]
