"""Общие фикстуры тестов.

Тесты идут против **настоящего** PostgreSQL 16, не против SQLite. Схема
использует нативные enum-типы, `GENERATED ... AS IDENTITY`, частичные и
выражательные индексы, `UNIQUE NULLS NOT DISTINCT`, отложенные составные внешние
ключи и коррелированные подзапросы с `NUMERIC` — на SQLite не воспроизводится
почти ничего из этого списка, и зелёные тесты означали бы проверку схемы,
которой не существует.

Поднять базу для тестов:

    docker run -d --name pg-test -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \\
        -e POSTGRES_DB=cost_test -p 5544:5432 postgres:16
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from decimal import Decimal

# Переменные окружения выставляются ДО первого импорта api.*: настройки
# читаются на импорте модуля api.core.config, и потом их уже не переопределить.
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5544")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "cost_test")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

import api.orm  # noqa: E402, F401 — регистрирует все таблицы в Base.metadata
from api.core.config import settings  # noqa: E402
from api.db.base import Base  # noqa: E402
from tests.fakes import FakeRateProvider  # noqa: E402

_MIN_SERVER_VERSION = 150000


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Движок на всю сессию тестов; схема пересоздаётся с нуля.

    `NullPool` обязателен: без него соединения asyncpg переживают тест и
    привязываются к другому циклу событий.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)

    async with engine.connect() as connection:
        version = await connection.scalar(text("SHOW server_version_num"))
        if int(version or 0) < _MIN_SERVER_VERSION:
            pytest.fail(
                f"Нужен PostgreSQL 15 или новее (текущая версия {version}): "
                "схема использует UNIQUE NULLS NOT DISTINCT"
            )

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def clean_db(engine: AsyncEngine) -> AsyncGenerator[None, None]:
    """Очищает все таблицы перед тестом одним оператором.

    Один `TRUNCATE` на все таблицы сразу, а не цикл: `CASCADE` в цикле удалял бы
    строки, которые следующая итерация уже не увидит. `RESTART IDENTITY`
    возвращает счётчики к началу, поэтому идентификаторы в тестах предсказуемы.
    """
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий с теми же настройками, что и в приложении."""
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def session(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Сессия для тестов репозиториев. База очищена."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def client(
    clean_db: None,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент поверх ASGI-приложения без реального сетевого слоя."""
    from api.db.session import get_session
    from api.main import create_app

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    # `ASGITransport` не выполняет lifespan, а клиент курсов собирается именно
    # там. Без подстановки любой запрос, считающий остаток или статистику, падал
    # бы на `app.state.rate_provider`. Фейк, а не настоящий клиент: тест не
    # должен ходить в сеть — он проверял бы доступность чужого сайта.
    app.state.rate_provider = FakeRateProvider(default_rate=Decimal("1"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
