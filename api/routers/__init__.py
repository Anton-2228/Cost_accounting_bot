"""Маршруты приложения.

Поверхность плоская: служебные эндпоинты `google_sheets_service` живут рядом с
пользовательскими и отличаются только тегом `service` в Swagger. Отдельного
префикса и аутентификации нет — api не публикуется наружу, безопасность
сетевая.

Порядок подключения важен только внутри роутера (литеральные маршруты до
параметрических); между роутерами префиксы не пересекаются.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.core.config import settings
from api.routers import (
    checks,
    imports,
    llm_usages,
    notifications,
    periods,
    records,
    sheet_mappings,
    sheet_sync_tasks,
    spreadsheets,
    system,
    transfers,
)

api_router = APIRouter(prefix=settings.api_v1_prefix)

api_router.include_router(spreadsheets.router)
api_router.include_router(records.router)
api_router.include_router(transfers.router)
api_router.include_router(periods.router)
api_router.include_router(checks.router)
api_router.include_router(llm_usages.router)
api_router.include_router(notifications.router)
api_router.include_router(imports.router)
api_router.include_router(sheet_mappings.router)
api_router.include_router(sheet_sync_tasks.router)

__all__ = ["api_router", "system"]
