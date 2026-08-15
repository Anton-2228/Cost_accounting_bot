"""Маршруты сервиса. Их два, и оба служебные: наблюдать и пнуть руками."""

from __future__ import annotations

from google_sheets_service.routers.system import router as system_router

__all__ = ["system_router"]
