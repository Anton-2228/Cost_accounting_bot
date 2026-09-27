"""Тесты эндпоинтов отложенных чеков."""

from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.orm.pending_check import PendingCheckORM
from api.orm.user_notification import UserNotificationORM
from tests import factories

_QR = "https://suf.purs.gov.rs/v/?vl=A1lNUVFXR0tDWU1RUVdHS0OLPwEAiz8BAPgiXQAA"
_KEY = "YMQQWGKC-YMQQWGKC-81803"

_ADD_BODY = {
    "kind": "SRB_SUF",
    "qr_raw": _QR,
    "external_key": _KEY,
    "error": "receipt_not_ready",
}

_NOTICE = {"total": "610.38", "purchased_at": "2026-08-26T23:30:00+00:00"}

_SAVE_BODY = {
    "kind": "SRB_SUF",
    "qr_raw": _QR,
    "external_key": _KEY,
    "raw_payload": {"invoice_number": _KEY},
    "fetched_at": "2026-08-27T13:00:00+00:00",
}


async def _spreadsheet_base(session: AsyncSession) -> tuple[int, str]:
    """Документ и адрес его отложенных чеков."""
    spreadsheet = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    assert spreadsheet.id is not None
    return spreadsheet.id, f"/api/v1/spreadsheets/{spreadsheet.id}/pending-checks"


async def _make_due(session: AsyncSession, *, window_age: timedelta = timedelta()) -> None:
    """Сдвигает срок повтора в прошлое, а начало окна — на `window_age` назад."""
    await session.execute(
        update(PendingCheckORM).values(
            next_attempt_at=func.now() - timedelta(seconds=1),
            window_started_at=func.now() - window_age,
        )
    )
    await session.commit()


async def _notifications(session: AsyncSession) -> list[UserNotificationORM]:
    """Все уведомления в порядке появления."""
    session.expire_all()
    return list(
        (await session.scalars(select(UserNotificationORM).order_by(UserNotificationORM.id))).all()
    )


async def test_pending_check_is_listed(client: AsyncClient, session: AsyncSession) -> None:
    """Отложенный чек виден в списке с первой попыткой и сроком следующей."""
    _, base = await _spreadsheet_base(session)

    added = await client.post(base, json=_ADD_BODY)
    assert added.status_code == 201
    data = added.json()["data"]
    assert data["attempts"] == 1
    assert data["expired_at"] is None
    assert data["last_error"] == "receipt_not_ready"

    listed = (await client.get(base)).json()["items"]
    assert [item["qr_raw"] for item in listed] == [_QR]


async def test_repeated_scan_returns_the_same_row(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Повторный скан не заводит вторую очередь попыток."""
    _, base = await _spreadsheet_base(session)

    first = (await client.post(base, json=_ADD_BODY)).json()["data"]
    second = await client.post(base, json=_ADD_BODY)
    assert second.status_code == 201
    assert second.json()["data"]["id"] == first["id"]
    assert len((await client.get(base)).json()["items"]) == 1


async def test_saved_check_cannot_be_deferred(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Уже сохранённый чек не откладывается — фон спрашивал бы о нём зря."""
    spreadsheet_id, base = await _spreadsheet_base(session)
    checks = f"/api/v1/spreadsheets/{spreadsheet_id}/checks"
    assert (await client.post(checks, json=_SAVE_BODY)).status_code == 201

    deferred = await client.post(base, json=_ADD_BODY)
    assert deferred.status_code == 409
    assert deferred.json()["details"]["reason"] == "check_already_saved"


async def test_saving_the_check_removes_it_from_pending(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Сохранённый чек ждать больше незачем — строка исчезает той же транзакцией.

    Уведомления без `notice` нет: чек сохраняет тот, кто смотрит на экран.
    """
    spreadsheet_id, base = await _spreadsheet_base(session)
    await client.post(base, json=_ADD_BODY)

    saved = await client.post(f"/api/v1/spreadsheets/{spreadsheet_id}/checks", json=_SAVE_BODY)
    assert saved.status_code == 201
    assert (await client.get(base)).json()["items"] == []
    assert await _notifications(session) == []


async def test_background_save_notifies_the_user(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Фон сохранил чек — бот скажет, какой: сумма и день покупки по поясу документа."""
    spreadsheet_id, base = await _spreadsheet_base(session)
    await client.post(base, json=_ADD_BODY)

    saved = await client.post(
        f"/api/v1/spreadsheets/{spreadsheet_id}/checks",
        json={**_SAVE_BODY, "notice": _NOTICE},
    )
    assert saved.status_code == 201

    [notification] = await _notifications(session)
    assert notification.kind == "PENDING_CHECK"
    assert notification.code == "check_added"
    # 23:30 UTC 26 августа — это уже 27 августа в поясе документа.
    assert notification.params == {"total": "610.38", "currency": "RSD", "day": "2026-08-27"}


async def test_claim_due_takes_only_ripe_checks(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Фон забирает только чеки, у которых подошёл срок, и не берёт их дважды."""
    _, base = await _spreadsheet_base(session)
    await client.post(base, json=_ADD_BODY)

    assert (await client.post("/api/v1/pending-checks/claim")).json()["items"] == []

    await _make_due(session)
    claimed = (await client.post("/api/v1/pending-checks/claim")).json()["items"]
    assert [item["external_key"] for item in claimed] == [_KEY]
    assert (await client.post("/api/v1/pending-checks/claim")).json()["items"] == []


async def test_background_failure_backs_off(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Неудача фона удваивает паузу и снимает захват."""
    _, base = await _spreadsheet_base(session)
    await client.post(base, json=_ADD_BODY)
    await _make_due(session)
    [claimed] = (await client.post("/api/v1/pending-checks/claim")).json()["items"]

    failed = await client.post(
        f"/api/v1/pending-checks/{claimed['id']}/fail",
        json={"error": "receipt_not_ready", "notice": _NOTICE},
    )
    assert failed.status_code == 204

    session.expire_all()
    row = await session.get(PendingCheckORM, claimed["id"])
    assert row is not None
    assert row.attempts == 2
    assert row.claimed_at is None
    assert row.expired_at is None
    now = await session.scalar(select(func.now()))
    assert now is not None
    delay = row.next_attempt_at - now
    expected = timedelta(seconds=constants.PENDING_CHECK_RETRY_BASE_SECONDS * 2)
    assert expected - timedelta(minutes=1) < delay <= expected


async def test_window_expiry_stops_background_and_notifies(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Через неделю фон сдаётся: чек истекает, бот сообщает — один раз."""
    _, base = await _spreadsheet_base(session)
    await client.post(base, json=_ADD_BODY)
    await _make_due(session, window_age=timedelta(days=8))
    [claimed] = (await client.post("/api/v1/pending-checks/claim")).json()["items"]

    fail_url = f"/api/v1/pending-checks/{claimed['id']}/fail"
    await client.post(fail_url, json={"error": "receipt_not_ready", "notice": _NOTICE})

    [listed] = (await client.get(base)).json()["items"]
    assert listed["expired_at"] is not None

    [notification] = await _notifications(session)
    assert notification.code == "check_expired"

    # Истёкший чек фон больше не берёт, даже когда срок подошёл.
    await _make_due(session, window_age=timedelta(days=8))
    assert (await client.post("/api/v1/pending-checks/claim")).json()["items"] == []


async def test_manual_failure_reopens_expired_check(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Неудачный ручной повтор возвращает истёкший чек в работу с новым окном."""
    _, base = await _spreadsheet_base(session)
    pending_id = (await client.post(base, json=_ADD_BODY)).json()["data"]["id"]
    await session.execute(update(PendingCheckORM).values(expired_at=func.now(), attempts=9))
    await session.commit()

    claimed = await client.post(f"{base}/{pending_id}/claim")
    assert claimed.status_code == 200

    await client.post(
        f"/api/v1/pending-checks/{pending_id}/fail",
        json={"error": "receipt_not_ready", "manual": True, "notice": _NOTICE},
    )
    [listed] = (await client.get(base)).json()["items"]
    assert listed["expired_at"] is None
    assert listed["attempts"] == 1
    assert await _notifications(session) == []


async def test_claimed_check_is_busy_for_manual_retry(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Пока чек спрашивает фон, ручной повтор получает 409, а не второй запрос."""
    _, base = await _spreadsheet_base(session)
    pending_id = (await client.post(base, json=_ADD_BODY)).json()["data"]["id"]
    await _make_due(session)
    await client.post("/api/v1/pending-checks/claim")

    busy = await client.post(f"{base}/{pending_id}/claim")
    assert busy.status_code == 409
    assert busy.json()["details"]["reason"] == "pending_check_busy"


async def test_fail_after_save_is_quietly_accepted(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Отчёт о строке, которой уже нет, — не ошибка: чек успели сохранить."""
    spreadsheet_id, base = await _spreadsheet_base(session)
    pending_id = (await client.post(base, json=_ADD_BODY)).json()["data"]["id"]
    await client.post(f"/api/v1/spreadsheets/{spreadsheet_id}/checks", json=_SAVE_BODY)

    failed = await client.post(
        f"/api/v1/pending-checks/{pending_id}/fail",
        json={"error": "receipt_not_ready", "notice": _NOTICE},
    )
    assert failed.status_code == 204


async def test_delete_removes_pending_check(client: AsyncClient, session: AsyncSession) -> None:
    """Удалённый чек исчезает из списка; повторное удаление — 404."""
    _, base = await _spreadsheet_base(session)
    pending_id = (await client.post(base, json=_ADD_BODY)).json()["data"]["id"]

    assert (await client.delete(f"{base}/{pending_id}")).status_code == 204
    assert (await client.get(base)).json()["items"] == []
    assert (await client.delete(f"{base}/{pending_id}")).status_code == 404


async def test_foreign_pending_check_is_invisible(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    """Чужой отложенный чек нельзя ни удалить, ни повторить — 404."""
    _, base = await _spreadsheet_base(session)
    pending_id = (await client.post(base, json=_ADD_BODY)).json()["data"]["id"]

    other = await factories.create_spreadsheet(session, ready=True)
    await session.commit()
    foreign = f"/api/v1/spreadsheets/{other.id}/pending-checks/{pending_id}"
    assert (await client.delete(foreign)).status_code == 404
    assert (await client.post(f"{foreign}/claim")).status_code == 404
