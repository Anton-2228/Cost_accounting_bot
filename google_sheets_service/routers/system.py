"""Служебные эндпоинты: наблюдение и ручной запуск прохода."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from google_sheets_service.sync.engine import SyncEngine

router = APIRouter(tags=["system"])


def _engine(request: Request) -> SyncEngine:
    """Достаёт движок из состояния приложения."""
    engine = getattr(request.app.state, "engine", None)
    if engine is None:  # pragma: no cover — возможно только при сбое сборки
        raise RuntimeError("Движок не инициализирован в app.state")
    return engine


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Состояние сервиса и итог последнего прохода.

    Отдаёт не «жив ли процесс», а что он успел сделать: сервис без входящих
    запросов иначе выглядел бы здоровым и молча не разбирая очередь. Это вся
    наблюдаемость, которая здесь есть, и её достаточно — счётчики прохода
    сразу показывают, берутся ли задачи и сколько из них падает.
    """
    engine = _engine(request)
    report = engine.last_report
    return {
        "status": "ok",
        "is_running": engine.is_running,
        "last_tick": None if report is None else report.as_dict(),
    }


@router.post("/sync")
async def trigger_sync(request: Request) -> dict[str, Any]:
    """Выполняет один проход прямо сейчас.

    Нужен для проверки руками: ждать очередного прохода, меняя что-то в
    документе, неудобно. Если проход уже идёт, движок вернёт отметку о пропуске
    — это не ошибка, а ровно то, что произошло.
    """
    return (await _engine(request).run_once()).as_dict()
