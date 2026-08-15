"""Тесты системных эндпоинтов."""

from __future__ import annotations

from httpx import AsyncClient


async def test_health_reports_liveness(client: AsyncClient) -> None:
    """`/health` отвечает, пока процесс жив."""
    response = await client.get("/health")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}


async def test_readiness_checks_postgres(client: AsyncClient) -> None:
    """`/health/ready` дотягивается до Postgres.

    Healthcheck контейнера смотрит именно сюда: в старой версии он проверял
    `/health`, который до БД не доходил, и бот стартовал против api, не
    способного обслужить ни один запрос.
    """
    response = await client.get("/health/ready")

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready", "checks": {"postgres": "ok"}}


async def test_unknown_route_returns_error_envelope(client: AsyncClient) -> None:
    """Неизвестный маршрут отвечает 404 в общем формате FastAPI."""
    response = await client.get("/api/v1/nope")

    assert response.status_code == 404
