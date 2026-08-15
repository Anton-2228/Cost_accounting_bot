"""Async-движок SQLAlchemy и фабрика сессий."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.core.config import settings

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    future=True,
)

# expire_on_commit=False обязателен. По умолчанию SQLAlchemy после commit()
# помечает все ORM-объекты сессии протухшими, и следующее обращение к атрибуту
# молча уходит в БД за свежим SELECT. В async такая неявная подгрузка выполняется
# внутри доступа к атрибуту, где негде поставить await, — и падает с
# MissingGreenlet. Плюс это лишние запросы: репозиторий уже сделал flush/refresh
# и все поля на руках.
session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
