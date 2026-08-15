"""Системные эндпоинты: liveness и readiness."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.session import get_session

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: процесс запущен и отвечает."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    """Readiness: Postgres доступен.

    Healthcheck контейнера должен смотреть именно сюда, а не на `/health`.
    В старой версии compose проверял `/health`, который до БД не дотягивался, и
    бот стартовал против api, не способного обслужить ни один запрос.
    """
    await session.execute(text("SELECT 1"))
    return {"status": "ready", "checks": {"postgres": "ok"}}
