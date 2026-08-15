"""Сборка FastAPI-приложения."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.core.config import settings
from api.core.logging import get_logger, setup_logging
from api.db.engine import engine, session_factory
from api.exceptions.handlers import register_exception_handlers
from api.routers import api_router, system
from api.tasks import NotificationLoop, RolloverLoop

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Жизненный цикл приложения.

    Схему БД здесь не создаём: за неё отвечает `alembic upgrade head` в
    точке входа контейнера. Прежняя версия звала `create_all` при каждом старте,
    из-за чего изменение модели молча не применялось к существующей таблице, а
    флаг `DROP_DB=True` в окружении стирал все данные без единого вопроса.

    Здесь же живёт фоновая смена учётного месяца. Она берёт на каждый документ
    рекомендательную блокировку в Postgres, поэтому нескольких воркеров api не
    боится.

    Рядом — рассылка уведомлений в бота. Она запускается только при заданном
    `BOT_NOTIFY_URL`: api обязан подниматься и без бота — в тестах, в одиночном
    прогоне и до того, как бот развёрнут.
    """
    logger.info("Запуск приложения «%s»", settings.app_name)
    rollover = RolloverLoop(session_factory)
    app.state.rollover = rollover
    await rollover.start()

    notifications: NotificationLoop | None = None
    if settings.bot_notify_url:
        notifications = NotificationLoop(
            session_factory,
            notify_url=settings.bot_notify_url,
            interval_seconds=settings.notification_push_interval_seconds,
            timeout_seconds=settings.notification_push_timeout_seconds,
        )
        await notifications.start()
    else:
        logger.warning("BOT_NOTIFY_URL не задан — уведомления копятся, но не рассылаются")
    app.state.notifications = notifications

    yield

    if notifications is not None:
        await notifications.stop()
    await rollover.stop()
    await engine.dispose()
    logger.info("Остановка приложения")


def create_app() -> FastAPI:
    """Создаёт и конфигурирует экземпляр FastAPI."""
    setup_logging()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Системные эндпоинты живут вне версионного префикса: healthcheck не должен
    # ломаться при переходе на /api/v2.
    app.include_router(system.router)
    app.include_router(api_router)

    return app


app = create_app()
