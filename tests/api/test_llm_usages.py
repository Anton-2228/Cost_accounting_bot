"""Тесты эндпоинта учёта обращений к модели."""

from __future__ import annotations

from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.orm.llm_usage import LlmUsageORM
from tests import factories

_USAGE_BODY = {
    "operation": "SUGGEST_PRODUCT_TYPES",
    "entity_kind": "CHECK",
    "entity_id": 42,
    "model": "anthropic/claude-sonnet-4.5",
    "prompt_tokens": 1200,
    "completion_tokens": 80,
    "total_tokens": 1280,
    "cost": "0.0004212",
    "raw_usage": {
        "prompt_tokens": 1200,
        "completion_tokens": 80,
        "total_tokens": 1280,
        "cost": 0.0004212,
        "prompt_tokens_details": {"cached_tokens": 1024},
    },
}


async def test_usage_is_recorded_with_cost_intact(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Замер сохраняется, и доли цента не округляются.

    Ради этого у `cost` своя точность: денежные `Numeric(14, 2)` записали бы
    сюда ноль, и вся таблица отвечала бы «ничего не потрачено».
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages",
        json=_USAGE_BODY,
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert Decimal(data["cost"]) == Decimal("0.0004212")
    assert data["model"] == "anthropic/claude-sonnet-4.5"
    assert data["entity_id"] == 42

    stored = (await session.scalars(select(LlmUsageORM))).one()
    assert stored.cost == Decimal("0.0004212")
    # Провайдер-специфичное уезжает в JSONB целиком, а не по колонкам.
    assert stored.raw_usage["prompt_tokens_details"] == {"cached_tokens": 1024}


async def test_usage_without_cost_is_recorded(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Провайдер без цены не мешает учёту токенов.

    Пусто означает «неизвестно» и обязано отличаться от нуля: иначе сумма за
    месяц занижалась бы молча.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages",
        json={**_USAGE_BODY, "cost": None},
    )

    assert response.status_code == 201
    assert response.json()["data"]["cost"] is None


async def test_usage_without_entity_is_recorded(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Обращение вне какой-либо сущности выразимо: пара необязательна."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages",
        json={**_USAGE_BODY, "entity_kind": None, "entity_id": None},
    )

    assert response.status_code == 201
    assert response.json()["data"]["entity_kind"] is None


async def test_half_filled_entity_pair_is_422(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Вид сущности без идентификатора — 422, а не ошибка целостности.

    То же стережёт `CHECK` в БД, но клиенту нечем отличить нарушение схемы от
    поломки сервера, если ответом будет 500.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages",
        json={**_USAGE_BODY, "entity_id": None},
    )

    assert response.status_code == 422


async def test_unknown_operation_is_422(client: AsyncClient, session: AsyncSession) -> None:
    """Неизвестный вид операции отсекается схемой.

    Вид — нативный enum в БД, и строка мимо него дошла бы до вставки, где
    превратилась бы в невнятную ошибку драйвера.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    response = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages",
        json={**_USAGE_BODY, "operation": "SUGGEST_SOMETHING"},
    )

    assert response.status_code == 422


async def test_usage_for_unknown_spreadsheet_is_404(client: AsyncClient) -> None:
    """Замер по несуществующему документу — 404."""
    response = await client.post("/api/v1/spreadsheets/999999/llm-usages", json=_USAGE_BODY)

    assert response.status_code == 404


async def test_usage_for_unlinked_spreadsheet_is_404(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """По отвязанному документу писать нечего: он больше не ведётся.

    Уже записанные замеры при этом остаются — деньги потрачены, и сумма за
    прошлый месяц не должна меняться задним числом.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    base = f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages"
    assert (await client.post(base, json=_USAGE_BODY)).status_code == 201

    assert (
        await client.delete(f"/api/v1/spreadsheets/{spreadsheet.id}")
    ).status_code == 204

    assert (await client.post(base, json=_USAGE_BODY)).status_code == 404
    assert len((await session.scalars(select(LlmUsageORM))).all()) == 1


async def test_usages_are_listed_in_order(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Чтение отдаёт замеры документа по времени.

    Порядок не украшение: отчёт раскладывает их по учётным периодам, и
    хронология — то, в чём он их и ожидает.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    base = f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages"
    assert (await client.post(base, json=_USAGE_BODY)).status_code == 201
    assert (
        await client.post(base, json={**_USAGE_BODY, "cost": "0.0000900"})
    ).status_code == 201

    response = await client.get(base)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [Decimal(item["cost"]) for item in items] == [
        Decimal("0.0004212"),
        Decimal("0.0000900"),
    ]
    # `raw_usage` наружу не отдаётся: он нужен будущим вопросам к базе, а
    # клиенту — нет, он сам его и прислал.
    assert "raw_usage" not in items[0]


async def test_unknown_cost_stays_unknown_on_read(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Пустая цена доезжает как `null`, а не как ноль.

    Ноль означал бы бесплатный вызов, и сумма занижалась бы ровно на
    неизвестное — молча, без единого признака в отчёте.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    base = f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages"
    assert (await client.post(base, json={**_USAGE_BODY, "cost": None})).status_code == 201

    response = await client.get(base)

    assert response.json()["items"][0]["cost"] is None


async def test_usages_of_unlinked_spreadsheet_are_readable(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Отвязанный документ читается наравне с живым.

    Это ровно тот случай, ради которого чтение и появилось: расход на модель не
    отменяется тем, что учёт по документу больше не ведут. Писать в такой
    документ по-прежнему нельзя.
    """
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()
    base = f"/api/v1/spreadsheets/{spreadsheet.id}/llm-usages"
    assert (await client.post(base, json=_USAGE_BODY)).status_code == 201
    assert (
        await client.delete(f"/api/v1/spreadsheets/{spreadsheet.id}")
    ).status_code == 204

    response = await client.get(base)

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


async def test_reading_unknown_spreadsheet_is_404(client: AsyncClient) -> None:
    """Несуществующий документ — 404, а не пустой список.

    Пустой список означал бы «этот документ ничего не тратил», и опечатка в
    идентификаторе выглядела бы как ответ.
    """
    response = await client.get("/api/v1/spreadsheets/999999/llm-usages")

    assert response.status_code == 404
    assert response.json()["details"] == {"resource": "spreadsheet"}
