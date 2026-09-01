"""Точка входа сервиса: сборка объектов и их закрытие."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from checks_service.auth.init_data import InitDataVerifier
from checks_service.config import settings
from checks_service.enums import CheckKind
from checks_service.exceptions import register_exception_handlers
from checks_service.formats.registry import FormatRegistry
from checks_service.formats.ru_fns import ProverkachekaFetcher, RuFnsQrParser
from checks_service.formats.srb_suf import SrbSufQrParser, SufFetcher
from checks_service.logging import get_logger, setup_logging
from checks_service.main_api import ApiGateway
from checks_service.routers import mini_app_router, system_router
from checks_service.services.check_intake import CheckIntakeService

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Собирает граф объектов и аккуратно всё закрывает.

    Граф собирается здесь, а не в модуле: клиенты `httpx` заводят соединения, и
    делать это на импорте значило бы лезть в сеть при любом обращении к
    модулю — в том числе из тестов.

    Реестр форматов — единственное место, где перечислены поддерживаемые чеки.
    Следующий добавится сюда двумя строками: парсер в список и фетчер в словарь.

    Порядок парсеров значения не имеет: `matches` у них взаимоисключающие —
    один требует пар «ключ=значение», другой ссылку на конкретный хост.
    """
    api = ApiGateway(settings.api_base_url, timeout=settings.api_timeout_seconds)
    registry = FormatRegistry(
        parsers=[RuFnsQrParser(), SrbSufQrParser()],
        fetchers={
            CheckKind.RU_FNS: ProverkachekaFetcher(
                settings.proverkacheka_base_url,
                token=settings.proverkacheka_api_token,
                timeout=settings.proverkacheka_timeout_seconds,
            ),
            CheckKind.SRB_SUF: SufFetcher(
                settings.suf_base_url,
                timeout=settings.suf_timeout_seconds,
            ),
        },
    )

    app.state.api = api
    app.state.registry = registry
    app.state.intake = CheckIntakeService(registry=registry, api=api)
    app.state.verifier = InitDataVerifier(
        settings.telegram_bot_token,
        max_age_seconds=settings.init_data_max_age_seconds,
    )

    logger.info(
        "Сервис запущен, api по адресу %s, разрешённых пользователей: %s",
        settings.api_base_url,
        len(settings.permitted_telegram_ids),
    )
    try:
        yield
    finally:
        await registry.aclose()
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
    app.include_router(mini_app_router)
    return app


app = create_app()
