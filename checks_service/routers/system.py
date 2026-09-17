"""Служебные эндпоинты: наблюдение."""

from __future__ import annotations

from fastapi import APIRouter, Response

from checks_service import metrics

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Короткий статус для docker-healthcheck."""
    return {"status": "ok"}


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Метрики пайплайна чеков для Prometheus.

    Маршрут живёт вне `/api/v1`, рядом с `/health`, и это не косметика:
    веб-сервер хоста проксирует наружу только `/api/`
    (`deploy/nginx/mini_app.conf.example`), поэтому `/metrics` из интернета не
    достаётся. Свойство несущее — в метриках есть `telegram_id`, — и открыть
    этот путь наружу значит выложить, кто и когда сканировал чеки. Prometheus
    ходит сюда по docker-сети, по имени сервиса.

    Аутентификации нет по той же причине: снаружи запрос сюда не доходит, а
    внутри сети её пришлось бы выдавать Prometheus'у, и секрет лежал бы в двух
    местах вместо одного.
    """
    body, content_type = metrics.render()
    return Response(content=body, media_type=content_type)
