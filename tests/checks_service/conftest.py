"""Фикстуры тестов `checks_service`.

Переменные окружения выставляются ДО первого импорта `checks_service.*`:
настройки читаются на импорте модуля `checks_service.config`, и потом их уже не
переопределить. Токен здесь заведомо ненастоящий — им подписывается тестовая
`initData`, и проверяется она тем же кодом, что работает в бою.
"""

from __future__ import annotations

import os

BOT_TOKEN = "123456:TEST-BOT-TOKEN"
ALLOWED_ID = 555_000_111
STRANGER_ID = 999_000_222

os.environ.setdefault("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", str(ALLOWED_ID))
os.environ.setdefault("API_BASE_URL", "http://api.test/api/v1")
os.environ.setdefault("PROVERKACHEKA_API_TOKEN", "test-token")

# Импорты сервиса — только ниже, когда окружение уже выставлено.
from collections.abc import AsyncGenerator, Iterator  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from checks_service import metrics  # noqa: E402
from checks_service.auth.init_data import InitDataVerifier  # noqa: E402
from checks_service.enums import CheckKind  # noqa: E402
from checks_service.formats.registry import FormatRegistry  # noqa: E402
from checks_service.formats.ru_fns.parser import RuFnsQrParser  # noqa: E402
from checks_service.main import create_app  # noqa: E402
from checks_service.main_api.spreadsheets import Spreadsheet  # noqa: E402
from checks_service.services.check_intake import CheckIntakeService  # noqa: E402
from tests.checks_service.factories import (  # noqa: E402
    PROVERKACHEKA_PAYLOAD,
    RU_FNS_QR,
    make_init_data,
)
from tests.checks_service.fakes import FakeApiGateway, FakeFetcher  # noqa: E402

PREVIEW_URL = "/api/v1/mini-app/checks/preview"
CHECKS_URL = "/api/v1/mini-app/checks"
ME_URL = "/api/v1/mini-app/me"
METRICS_URL = "/metrics"


class Bench:
    """Собранное приложение вместе с фейками, до которых надо дотянуться."""

    def __init__(self, client: AsyncClient, api: FakeApiGateway, fetcher: FakeFetcher) -> None:
        self.client = client
        self.api = api
        self.fetcher = fetcher

    def auth(self, telegram_id: int = ALLOWED_ID) -> dict[str, str]:
        """Заголовок с подписанной `initData`."""
        return {
            "Authorization": "tma " + make_init_data(
                telegram_id=telegram_id, bot_token=BOT_TOKEN
            )
        }

    async def preview(self, qr: str = RU_FNS_QR, **kwargs: Any) -> httpx.Response:
        """POST на распознавание."""
        return await self.client.post(PREVIEW_URL, json={"qr_raw": qr}, **kwargs)

    async def add(self, qr: str = RU_FNS_QR, **kwargs: Any) -> httpx.Response:
        """POST на добавление."""
        return await self.client.post(CHECKS_URL, json={"qr_raw": qr}, **kwargs)


@pytest.fixture
async def bench() -> AsyncGenerator[Bench, None]:
    """Приложение с фейковым api и фейковой расшифровкой.

    Приложение поднимается без lifespan (`ASGITransport` его не выполняет), а
    состояние собирается руками из фейков: настоящий граф ходил бы и в api, и
    во внешний сервис расшифровки.
    """
    api = FakeApiGateway()
    api.spreadsheets.spreadsheet = Spreadsheet(id=7, title="Мои расходы")
    fetcher = FakeFetcher(payload=PROVERKACHEKA_PAYLOAD)

    registry = FormatRegistry(parsers=[RuFnsQrParser()], fetchers={CheckKind.RU_FNS: fetcher})

    app = create_app()
    app.state.api = api
    app.state.registry = registry
    app.state.intake = CheckIntakeService(registry=registry, api=api)  # type: ignore[arg-type]
    app.state.verifier = InitDataVerifier(BOT_TOKEN, max_age_seconds=3600)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield Bench(client, api, fetcher)


@pytest.fixture(autouse=True)
def _clean_metrics() -> Iterator[None]:
    """Обнуляет метрики вокруг каждого теста.

    Счётчики — глобальные объекты в реестре `prometheus_client`, созданные на
    импорте модуля: между тестами они не пересоздаются и накопленное несут
    дальше. Фикстура автоматическая и обнуляет их с обеих сторон, потому что
    приращения оставляет любой тест, отправивший запрос, а не только
    `test_metrics.py`.
    """
    metrics.reset()
    yield
    metrics.reset()
