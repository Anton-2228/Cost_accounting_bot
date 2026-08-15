"""Точка входа сервиса: сборка объектов и запуск фонового цикла."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from google_sheets_service.config import settings
from google_sheets_service.exceptions import register_exception_handlers
from google_sheets_service.google.credentials import CredentialsLoader
from google_sheets_service.google.drive_client import GoogleDriveClient
from google_sheets_service.google.retry import RetryPolicy
from google_sheets_service.google.sheets_client import GoogleSheetsClient
from google_sheets_service.logging import get_logger, setup_logging
from google_sheets_service.main_api import ApiGateway
from google_sheets_service.routers import system_router
from google_sheets_service.scheduler import BackgroundScheduler
from google_sheets_service.sync.engine import SyncEngine
from google_sheets_service.sync.importer import SheetImporter
from google_sheets_service.sync.pacer import Pacer
from google_sheets_service.sync.redraw import SheetRedrawer
from google_sheets_service.sync.structure import StructureSynchronizer

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Собирает граф объектов, запускает цикл и аккуратно всё закрывает.

    Граф собирается здесь, а не в модуле: клиенты Google и `httpx` заводят
    соединения, и делать это на импорте значило бы лезть в сеть при любом
    обращении к модулю — в том числе из тестов.

    Событие остановки одно на цикл и `Pacer`: остановка прерывает и ожидание
    следующего прохода, и паузу между задачами, поэтому контейнер гасится за
    время текущей задачи, а не за сумму всех оставшихся пауз.
    """
    credentials = CredentialsLoader(settings).load()
    retry = RetryPolicy(
        max_retries=settings.google_max_retries,
        base_seconds=settings.google_retry_base_seconds,
        jitter_seconds=settings.google_retry_jitter_seconds,
    )
    sheets = GoogleSheetsClient(
        credentials,
        timeout_seconds=settings.google_timeout_seconds,
        retry=retry,
    )
    drive = GoogleDriveClient(
        credentials,
        timeout_seconds=settings.google_timeout_seconds,
        retry=retry,
    )
    api = ApiGateway(settings.api_base_url, timeout=settings.api_timeout_seconds)

    stop = asyncio.Event()
    redrawer = SheetRedrawer(api=api, sheets=sheets)
    engine = SyncEngine(
        api=api,
        sheets=sheets,
        structure=StructureSynchronizer(api=api, sheets=sheets, drive=drive),
        redrawer=redrawer,
        importer=SheetImporter(api=api, sheets=sheets, redrawer=redrawer),
        pacer=Pacer(
            interval_seconds=settings.tick_interval_seconds,
            jitter_seconds=settings.tick_jitter_seconds,
            stop=stop,
        ),
        claim_limit=settings.claim_limit,
    )
    scheduler = BackgroundScheduler(
        engine=engine,
        stop=stop,
        interval_seconds=settings.tick_interval_seconds,
        initial_delay_seconds=settings.initial_delay_seconds,
    )

    app.state.engine = engine
    app.state.scheduler = scheduler
    app.state.api = api

    await scheduler.start()
    logger.info("Сервис запущен, api по адресу %s", settings.api_base_url)
    try:
        yield
    finally:
        await scheduler.stop()
        await api.aclose()
        logger.info("Сервис остановлен")


def create_app() -> FastAPI:
    """Собирает приложение."""
    setup_logging()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(system_router)
    return app


app = create_app()
