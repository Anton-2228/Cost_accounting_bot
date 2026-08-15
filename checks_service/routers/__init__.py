"""Маршруты сервиса: служебный `/health` и два эндпоинта Mini App."""

from __future__ import annotations

from checks_service.routers.mini_app import router as mini_app_router
from checks_service.routers.system import router as system_router

__all__ = ["mini_app_router", "system_router"]
