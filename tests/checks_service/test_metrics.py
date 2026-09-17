"""Тесты метрик пайплайна чеков.

Проверяется не «метрика существует», а то, по какому именно признаку она
считается: успех — по появлению чека в api, отказ — по коду исключения,
длительность — по исходу похода во внешний сервис. Сами значения читаются из
реестра `prometheus_client`, а не разбором текста экспозиции: разбор проверял бы
формат библиотеки, а не наш замысел.
"""

from __future__ import annotations

import httpx
from prometheus_client import REGISTRY

from checks_service.exceptions import ApiError, ReceiptFetchError, ReceiptNotFoundError
from checks_service.main import create_app
from checks_service.metrics import UNKNOWN_TELEGRAM_ID
from tests.checks_service.conftest import ALLOWED_ID, ME_URL, METRICS_URL, STRANGER_ID, Bench

SRB_QR = "https://suf.purs.gov.rs/v/?vl=A1ZQMDI4NTE5"


def saves(telegram_id: int | str = ALLOWED_ID, kind: str = "RU_FNS") -> float | None:
    """Сколько чеков сохранено этим пользователем в этом формате."""
    return REGISTRY.get_sample_value(
        "receipt_saves_total",
        {"telegram_id": str(telegram_id), "kind": kind},
    )


def previews(telegram_id: int | str = ALLOWED_ID, kind: str = "RU_FNS") -> float | None:
    """Сколько плашек показано."""
    return REGISTRY.get_sample_value(
        "receipt_previews_total",
        {"telegram_id": str(telegram_id), "kind": kind},
    )


def failures(reason: str, stage: str = "save", telegram_id: int | str = ALLOWED_ID) -> float | None:
    """Сколько отказов с этим кодом на этой стадии."""
    return REGISTRY.get_sample_value(
        "receipt_failures_total",
        {"telegram_id": str(telegram_id), "stage": stage, "reason": reason},
    )


def fetches(outcome: str, kind: str = "RU_FNS") -> float | None:
    """Сколько походов во внешний сервис кончилось этим исходом."""
    return REGISTRY.get_sample_value(
        "receipt_fetch_seconds_count",
        {"kind": kind, "outcome": outcome},
    )


async def test_preview_is_counted_without_a_save(bench: Bench) -> None:
    """Плашка считается отдельно от сохранения: внешний сервис ещё не звали."""
    await bench.preview(headers=bench.auth())

    assert previews() == 1
    assert saves() is None
    assert fetches("ok") is None


async def test_save_counts_the_receipt_and_the_fetch(bench: Bench) -> None:
    """Успех — это строка в api, и вместе с ним засчитан поход за расшифровкой."""
    await bench.add(headers=bench.auth())

    assert saves() == 1
    assert fetches("ok") == 1


async def test_unknown_format_is_counted_before_any_external_call(bench: Bench) -> None:
    """Нераспознанный QR — отказ, а не показанная плашка и не поход в сервис."""
    await bench.add(SRB_QR, headers=bench.auth())

    assert failures("format_not_supported") == 1
    assert previews() is None
    # Гистограмма не тронута ни одним исходом: внешнего вызова не было вовсе.
    assert fetches("ok") is None
    assert fetches("error") is None


async def test_missing_receipt_is_not_counted_as_a_broken_service(bench: Bench) -> None:
    """«Чека нет в базе» отделено от сбоя сервиса и в метрике тоже.

    Это пришпиливает порядок `except` в замере: `ReceiptNotFoundError` —
    подкласс `ReceiptFetchError`, и при обратном порядке всякий ненайденный чек
    молча считался бы сбоем внешнего сервиса.
    """
    bench.fetcher.fail_with = ReceiptNotFoundError("Чек не найден в базе ФНС")

    await bench.add(headers=bench.auth())

    assert failures("receipt_not_found") == 1
    assert fetches("not_found") == 1
    assert fetches("error") is None
    assert saves() is None


async def test_broken_service_is_counted_as_an_error(bench: Bench) -> None:
    """Сбой расшифровки виден и в отказах, и в исходе замера."""
    bench.fetcher.fail_with = ReceiptFetchError("Сервис расшифровки чеков недоступен")

    await bench.add(headers=bench.auth())

    assert failures("receipt_fetch_failed") == 1
    assert fetches("error") == 1
    assert fetches("not_found") is None


async def test_repeated_receipt_is_counted_by_its_own_reason(bench: Bench) -> None:
    """Повтор чека — своя причина отказа, а не общая ошибка api."""
    bench.api.checks.already_saved = True

    await bench.add(headers=bench.auth())

    assert failures("check_already_saved") == 1
    assert saves() is None
    # Расшифровку уже потратили: дедупликацию знает api, а не этот сервис.
    assert fetches("ok") == 1


async def test_unavailable_api_is_counted_apart_from_the_external_service(bench: Bench) -> None:
    """Недоступное api и недоступный сервис расшифровки — разные причины."""
    bench.api.checks.fail_with = ApiError(httpx.codes.BAD_GATEWAY, "connection refused")

    await bench.add(headers=bench.auth())

    assert failures("api_error") == 1
    assert failures("receipt_fetch_failed") is None


async def test_user_without_table_is_counted_at_the_preview_stage(bench: Bench) -> None:
    """Стадия берётся из пути запроса, а не из вида отказа."""
    bench.api.spreadsheets.spreadsheet = None

    await bench.preview(headers=bench.auth())

    assert failures("spreadsheet_not_found", stage="preview") == 1
    assert failures("spreadsheet_not_found", stage="save") is None


async def test_stranger_cannot_create_a_series_of_their_own(bench: Bench) -> None:
    """Отказ постороннему считается под общей меткой, а не под его id.

    Метка пользователя ставится только после проверки списка допуска. Иначе
    всякий, раздобывший верную подпись Telegram, заводил бы новый временной ряд
    в хранилище метрик одним лишь стуком в сервис.
    """
    await bench.add(headers=bench.auth(STRANGER_ID))

    assert failures("forbidden", telegram_id=UNKNOWN_TELEGRAM_ID) == 1
    assert failures("forbidden", telegram_id=STRANGER_ID) is None


async def test_request_without_a_signature_is_counted_as_unknown(bench: Bench) -> None:
    """Без подписи пользователя нет вовсе — ряд тот же самый."""
    await bench.preview()

    assert failures("unauthorized", stage="preview", telegram_id=UNKNOWN_TELEGRAM_ID) == 1


async def test_paths_outside_the_receipt_pipeline_are_not_counted(bench: Bench) -> None:
    """Карта путей закрыта: отказ на `/me` метрику чеков не трогает.

    Наблюдение ограничено приёмом чеков намеренно. Будь карта открытой, метка
    стадии росла бы от любого стука в сервис, а с ней и число рядов.
    """
    bench.api.users.fail_with = ApiError(503, "api лежит")

    response = await bench.client.get(ME_URL, headers=bench.auth())

    assert response.status_code == 502
    assert REGISTRY.get_sample_value("receipt_failures_total", {}) is None
    assert failures("api_error") is None
    assert failures("api_error", stage="preview") is None


async def test_metrics_endpoint_serves_the_exposition(bench: Bench) -> None:
    """`/metrics` отдаёт то, что заберёт Prometheus."""
    await bench.add(headers=bench.auth())

    response = await bench.client.get(METRICS_URL)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "receipt_saves_total" in response.text


async def test_metrics_endpoint_needs_no_signature(bench: Bench) -> None:
    """Подписи `/metrics` не требует: снаружи запрос сюда не доходит.

    Наружу веб-сервер хоста проксирует только `/api/`, а Prometheus ходит по
    docker-сети. Потребуй маршрут подпись — секрет пришлось бы держать ещё и в
    конфигурации Prometheus.
    """
    assert (await bench.client.get(METRICS_URL)).status_code == 200


def test_app_can_be_built_twice() -> None:
    """Повторная сборка приложения не падает.

    Метрики создаются на импорте модуля, а не в фабрике. Перенеси их внутрь —
    и второй `create_app()` упал бы на `Duplicated timeseries`: в бою это
    незаметно (фабрика зовётся однажды), а в тестах — на каждом стенде.
    """
    create_app()
    create_app()
