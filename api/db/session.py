"""FastAPI-зависимость, отдающая async-сессию БД.

Границей транзакции управляет сервисный слой. Здесь сессия только создаётся на
время запроса и гарантированно закрывается; при необработанной ошибке
незакоммиченные изменения откатываются.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.engine import session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Создаёт `AsyncSession` на время обработки запроса."""
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
