"""Тесты эндпоинтов Mini App.

Приложение поднимается без lifespan (`ASGITransport` его не выполняет), а
состояние собирается руками из фейков: настоящий граф ходил бы и в api, и во
внешний сервис расшифровки.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from checks_service.auth.init_data import InitDataVerifier
from checks_service.enums import CheckKind
from checks_service.exceptions import ApiError, ReceiptFetchError, ReceiptNotFoundError
from checks_service.formats.registry import FormatRegistry
from checks_service.formats.ru_fns.parser import RuFnsQrParser
from checks_service.main import create_app
from checks_service.main_api.spreadsheets import Spreadsheet
from checks_service.services.check_intake import CheckIntakeService
from tests.checks_service.conftest import ALLOWED_ID, BOT_TOKEN, STRANGER_ID
from tests.checks_service.factories import (
    PROVERKACHEKA_PAYLOAD,
    RU_FNS_KEY,
    RU_FNS_QR,
    make_init_data,
)
from tests.checks_service.fakes import FakeApiGateway, FakeFetcher

PREVIEW_URL = "/api/v1/mini-app/checks/preview"
CHECKS_URL = "/api/v1/mini-app/checks"


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
    """Приложение с фейковым api и фейковой расшифровкой."""
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


async def test_preview_does_not_touch_the_paid_service(bench: Bench) -> None:
    """Плашка собирается из QR-строки, внешний сервис при этом молчит.

    Расшифровка платная и лимитированная: тратить её на чек, который
    пользователь ещё не подтвердил, нельзя.
    """
    response = await bench.preview(headers=bench.auth())

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "RU_FNS"
    assert body["spreadsheet_title"] == "Мои расходы"
    assert body["total"] == "1214.95"
    assert body["purchased_at"].startswith("2026-07-25T15:07")
    assert bench.fetcher.calls == []


async def test_add_fetches_then_saves_whole_payload(bench: Bench) -> None:
    """Добавление расшифровывает чек и кладёт ответ в api целиком."""
    response = await bench.add(headers=bench.auth())

    assert response.status_code == 201
    assert response.json() == {"id": 1, "kind": "RU_FNS"}

    assert len(bench.fetcher.calls) == 1
    assert len(bench.api.checks.saved) == 1
    saved = bench.api.checks.saved[0]
    assert saved["spreadsheet_id"] == 7
    assert saved["external_key"] == RU_FNS_KEY
    assert saved["qr_raw"] == RU_FNS_QR
    # Ответ внешнего сервиса уезжает как есть: суммы в копейках, ничего не
    # обрезано. Разбор возьмёт отсюда поля, о которых сейчас неизвестно, что
    # они понадобятся.
    assert saved["raw_payload"] == PROVERKACHEKA_PAYLOAD


async def test_unknown_format_is_refused_before_any_call(bench: Bench) -> None:
    """Незнакомый формат отсекается до обращений куда бы то ни было."""
    response = await bench.add("https://suf.purs.gov.rs/v/?vl=A1ZQMDI4NTE5", headers=bench.auth())

    assert response.status_code == 422
    assert response.json()["code"] == "format_not_supported"
    assert bench.fetcher.calls == []
    assert bench.api.checks.saved == []


async def test_failed_fetch_saves_nothing(bench: Bench) -> None:
    """Отказ внешнего сервиса не оставляет в БД получека.

    Чек в базе всегда полный: иначе разбору пришлось бы уметь работать с
    неполными, которых в норме не бывает.
    """
    bench.fetcher.fail_with = ReceiptFetchError("Сервис расшифровки чеков недоступен")

    response = await bench.add(headers=bench.auth())

    assert response.status_code == 502
    assert response.json()["code"] == "receipt_fetch_failed"
    assert bench.api.checks.saved == []


async def test_receipt_not_found_is_its_own_answer(bench: Bench) -> None:
    """«Чека нет в базе ФНС» — не сбой сервиса, и отвечать надо иначе."""
    bench.fetcher.fail_with = ReceiptNotFoundError("Чек не найден в базе ФНС")

    response = await bench.add(headers=bench.auth())

    assert response.status_code == 404
    assert response.json()["code"] == "receipt_not_found"


async def test_repeated_check_is_reported_as_already_saved(bench: Bench) -> None:
    """Повтор превращается в понятный ответ, а не в невнятный конфликт."""
    bench.api.checks.already_saved = True

    response = await bench.add(headers=bench.auth())

    assert response.status_code == 409
    assert response.json()["code"] == "check_already_saved"


async def test_user_without_table_is_told_what_to_do(bench: Bench) -> None:
    """Без таблицы чек некуда класть — и об этом говорится прямо."""
    bench.api.spreadsheets.spreadsheet = None

    response = await bench.preview(headers=bench.auth())

    assert response.status_code == 404
    assert response.json()["code"] == "spreadsheet_not_found"


async def test_unavailable_api_does_not_become_a_500(bench: Bench) -> None:
    """Недоступное api — 502 с кодом, а не пятисотка без объяснений."""
    bench.api.checks.fail_with = ApiError(httpx.codes.BAD_GATEWAY, "connection refused")

    response = await bench.add(headers=bench.auth())

    assert response.status_code == 502
    assert response.json()["code"] == "api_error"


async def test_request_without_signature_is_401(bench: Bench) -> None:
    """Без подписи Telegram — 401. Своих сессий у сервиса нет."""
    response = await bench.preview()

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert bench.api.spreadsheets.calls == []


async def test_stranger_with_valid_signature_is_403(bench: Bench) -> None:
    """Подпись верная, но такого telegram_id нет в списке разрешённых.

    Проверка не про приватность: расшифровка платная, и без списка любой, кто
    узнал адрес Mini App, жёг бы чужой лимит.
    """
    response = await bench.add(headers=bench.auth(STRANGER_ID))

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert bench.fetcher.calls == []


async def test_empty_qr_is_422(bench: Bench) -> None:
    """Пустая строка отсекается схемой запроса."""
    assert (await bench.add("", headers=bench.auth())).status_code == 422
