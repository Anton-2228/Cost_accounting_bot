"""Границы транзакции.

Репозитории делают только `flush`/`refresh` и никогда не коммитят: одна
пользовательская операция — это несколько записей в разные таблицы плюс строка
в очереди перерисовки листов, и они должны попасть в БД целиком или никак.
Коммитит сервисный слой ровно одним вызовом :func:`commit`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def commit(session: AsyncSession) -> None:
    """Фиксирует транзакцию сессии."""
    await session.commit()
