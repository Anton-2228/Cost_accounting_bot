"""Тесты эндпоинтов учётной таблицы."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests import factories

_PREFIX = "/api/v1/spreadsheets"


async def test_create_returns_envelope_and_201(client: AsyncClient) -> None:
    """Одиночный ресурс приезжает в конверте `data`."""
    response = await client.post(
        _PREFIX,
        json={"telegram_id": 4001, "title": "Мои расходы", "reset_day": 10},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["data"]["title"] == "Мои расходы"
    assert body["data"]["google_spreadsheet_id"] is None
    # Внутренние поля наружу не выдаются.
    assert "user_id" not in body["data"]


async def test_second_start_returns_409_envelope(client: AsyncClient) -> None:
    """Повторный /start — 409 с машинным кодом и причиной в details.

    Русский текст для пользователя подбирает бот по коду; здесь едет только код.
    """
    payload = {"telegram_id": 4002, "title": "Первая", "reset_day": 10}
    assert (await client.post(_PREFIX, json=payload)).status_code == 201

    response = await client.post(_PREFIX, json=payload)
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert body["details"] == {"reason": "spreadsheet_exists"}


async def test_unknown_reset_day_is_422(client: AsyncClient) -> None:
    """День сброса вне 1..28 отвергается схемой."""
    response = await client.post(
        _PREFIX,
        json={"telegram_id": 4003, "title": "Т", "reset_day": 31},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


async def test_unknown_field_is_rejected(client: AsyncClient) -> None:
    """Опечатка в имени поля — 422, а не молча проигнорированное поле."""
    response = await client.post(
        _PREFIX,
        json={"telegram_id": 4004, "title": "Т", "reset_day": 5, "rest_day": 7},
    )
    assert response.status_code == 422


async def test_get_by_telegram_id_is_not_shadowed_by_id_route(client: AsyncClient) -> None:
    """Литерал `by-telegram` не перехватывается маршрутом `/{spreadsheet_id}`."""
    await client.post(
        _PREFIX,
        json={"telegram_id": 4005, "title": "Т", "reset_day": 5},
    )

    found = await client.get(f"{_PREFIX}/by-telegram/4005")
    assert found.status_code == 200
    assert found.json()["data"]["title"] == "Т"

    missing = await client.get(f"{_PREFIX}/by-telegram/999999")
    assert missing.status_code == 404
    assert missing.json()["details"] == {"resource": "spreadsheet"}


async def test_catalogues_come_in_items_envelope(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Списки приезжают в конверте `items`, без метаданных пагинации."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await factories.create_category(session, spreadsheet, title="Еда")
    await factories.create_source(session, spreadsheet, title="Кошелёк")
    await session.commit()

    categories = await client.get(f"{_PREFIX}/{spreadsheet.id}/categories")
    assert categories.status_code == 200
    assert [item["title"] for item in categories.json()["items"]] == ["Еда"]

    sources = await client.get(f"{_PREFIX}/{spreadsheet.id}/sources")
    assert [item["title"] for item in sources.json()["items"]] == ["Кошелёк"]

    balances = await client.get(f"{_PREFIX}/{spreadsheet.id}/balances")
    assert balances.json()["items"][0]["balance"] == "0.00"


async def test_work_with_document_without_google_table_is_409(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Пока Google-таблицы нет, справочники недоступны: 409 с внятной причиной."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    response = await client.get(f"{_PREFIX}/{spreadsheet.id}/categories")
    assert response.status_code == 409
    assert response.json()["details"] == {"reason": "spreadsheet_not_ready"}


async def test_sync_is_accepted_not_completed(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Просьба вчитать листы возвращает 202: работа только поставлена в очередь."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    response = await client.post(f"{_PREFIX}/{spreadsheet.id}/sync")
    assert response.status_code == 202


async def test_access_lifecycle(client: AsyncClient, session: AsyncSession) -> None:
    """Доступ добавляется, ждёт выдачи и отмечается выданным."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    created = await client.post(
        f"{_PREFIX}/{spreadsheet.id}/accesses",
        json={"email": "user@example.com"},
    )
    assert created.status_code == 201
    access_id = created.json()["data"]["id"]
    assert created.json()["data"]["granted_at"] is None

    pending = await client.get(f"{_PREFIX}/{spreadsheet.id}/accesses?pending_only=true")
    assert [item["id"] for item in pending.json()["items"]] == [access_id]

    granted = await client.post(
        f"{_PREFIX}/{spreadsheet.id}/accesses/{access_id}/granted"
    )
    assert granted.status_code == 204

    pending = await client.get(f"{_PREFIX}/{spreadsheet.id}/accesses?pending_only=true")
    assert pending.json()["items"] == []


async def test_google_id_endpoint_makes_document_ready(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Служебная привязка документа делает таблицу готовой и оповещает пользователя."""
    spreadsheet = await factories.create_spreadsheet(session)
    await session.commit()

    response = await client.post(
        f"{_PREFIX}/{spreadsheet.id}/google-id",
        json={"google_spreadsheet_id": "google-xyz"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["google_spreadsheet_id"] == "google-xyz"

    notifications = await client.get(f"{_PREFIX}/{spreadsheet.id}/notifications")
    assert [item["kind"] for item in notifications.json()["items"]] == ["TABLE_READY"]


async def test_delete_returns_204_and_then_404(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Удаление отвечает 204, повторное обращение — 404."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    assert (await client.delete(f"{_PREFIX}/{spreadsheet.id}")).status_code == 204
    assert (await client.get(f"{_PREFIX}/{spreadsheet.id}")).status_code == 404


async def test_include_deleted_returns_catalogues_for_archive_sheets(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """`?include_deleted=true` отдаёт удалённые справочники.

    Ими перерисовываются архивные листы: операция удалённой категории остаётся в
    реестре, и колонке `Category` нужно её название. По умолчанию удалённых нет —
    лист `Categories` не должен показывать то, что пользователь убрал.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    category = await factories.create_category(session, spreadsheet, title="Былое")
    source = await factories.create_source(session, spreadsheet, title="Закрытый")
    await session.commit()

    base = f"{_PREFIX}/{spreadsheet.id}"
    imported = await client.post(
        f"{base}/import/categories",
        json={"rows": [[str(category.id), "", "", "", "", "", ""],
                       ["", "1", "0", "1", "Новая", "", ""]]},
    )
    assert imported.json()["data"]["deleted"] == 1

    removed = await client.post(
        f"{base}/import/bills",
        json={"rows": [[str(source.id), "", "", "", "", ""],
                       ["", "1", "Новый", "", "0", ""]]},
    )
    assert removed.json()["data"]["deleted"] == 1

    alive_categories = await client.get(f"{base}/categories")
    assert [item["title"] for item in alive_categories.json()["items"]] == ["Новая"]

    with_deleted = await client.get(f"{base}/categories", params={"include_deleted": "true"})
    assert [item["title"] for item in with_deleted.json()["items"]] == ["Былое", "Новая"]

    sources_with_deleted = await client.get(
        f"{base}/sources", params={"include_deleted": "true"}
    )
    assert [item["title"] for item in sources_with_deleted.json()["items"]] == [
        "Закрытый",
        "Новый",
    ]

    # Баланс закрытого счёта не показывается: это текущее состояние, не история.
    balances = await client.get(f"{base}/balances")
    assert [item["title"] for item in balances.json()["items"]] == ["Новый"]


async def test_rejected_access_is_removed_and_reported(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Почта, которую Google не принял, удаляется и попадает в уведомления.

    Оставить её ждущей выдачи нельзя: `granted_at IS NULL` означает «выдать
    предстоит», и неверный адрес попадал бы в каждую последующую сверку скелета,
    порождая по уведомлению на каждую.
    """
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    created = await client.post(
        f"{_PREFIX}/{spreadsheet.id}/accesses",
        json={"email": "broken@example.com"},
    )
    access_id = created.json()["data"]["id"]

    failed = await client.post(
        f"{_PREFIX}/{spreadsheet.id}/accesses/{access_id}/failed"
    )
    assert failed.status_code == 204

    accesses = await client.get(f"{_PREFIX}/{spreadsheet.id}/accesses")
    assert accesses.json()["items"] == []

    notifications = await client.get(f"{_PREFIX}/{spreadsheet.id}/notifications")
    texts = [item["text"] for item in notifications.json()["items"]]
    assert any("broken@example.com" in text for text in texts)


async def test_failed_access_of_another_spreadsheet_is_404(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Чужой доступ отметить нельзя: документы изолированы друг от друга."""
    first = await factories.create_spreadsheet(session, ready=True)
    second = await factories.create_spreadsheet(session, ready=True)
    await session.commit()

    created = await client.post(
        f"{_PREFIX}/{first.id}/accesses",
        json={"email": "user@example.com"},
    )
    access_id = created.json()["data"]["id"]

    response = await client.post(f"{_PREFIX}/{second.id}/accesses/{access_id}/failed")
    assert response.status_code == 404
