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

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:AAHtesttesttesttesttesttesttesttest")
os.environ.setdefault("API_BASE_URL", "http://api:8000/api/v1")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "")
# Ключ модели обязателен так же, как токен бота: без него разбор чека работать
# не может. В тестах модель подменяется фейком и по сети не ходит ни разу.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_MODEL", "test-model")

import pytest  # noqa: E402

from telegram_bot.api_client.models import (  # noqa: E402
    Category,
    CategoryKind,
    EntityStatus,
)
from telegram_bot.i18n import language as i18n_language  # noqa: E402
from telegram_bot.i18n.language import Language  # noqa: E402

#: Тесты бота сверяют тексты с русским каталогом: он исходный, с него
#: переводятся остальные. Язык подменяется здесь, на импорте, а не фикстурой:
#: часть надписей тесты берут из каталога в константах модуля и в
#: `parametrize`, то есть ещё при сборе тестов, до всякой фикстуры.
i18n_language.DEFAULT_LANGUAGE = Language.RU


class FakeLanguages:
    """Языки пользователей без api: у всех один язык, пока его не сменили.

    Помнит, у кого спрашивали и кому меняли: `Manager` обязан не спрашивать
    язык постороннего, а выбор языка — записать выбранное.
    """

    def __init__(self, language: Language = Language.RU) -> None:
        self.default = language
        self.changed: dict[int, Language] = {}
        self.resolved: list[int] = []

    async def resolve(self, telegram_id: int) -> Language:
        """Язык пользователя."""
        self.resolved.append(telegram_id)
        return self.changed.get(telegram_id, self.default)

    async def change(self, telegram_id: int, language: Language) -> Language:
        """Записывает язык."""
        self.changed[telegram_id] = language
        return language


def make_category(
    *,
    category_id: int = 1,
    title: str = "Продукты",
    kind: CategoryKind = CategoryKind.EXPENSE,
    associations: list[str] | None = None,
    is_default: bool = False,
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
        is_default=is_default,
        associations=associations if associations is not None else [title.lower()],
        product_types=[],
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


