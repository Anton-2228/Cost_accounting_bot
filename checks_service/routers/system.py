"""Служебные эндпоинты: наблюдение."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Короткий статус для docker-healthcheck."""
    return {"status": "ok"}
