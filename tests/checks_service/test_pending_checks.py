"""Тесты отложенных чеков: список, ручной повтор, удаление и фоновый проход."""

from __future__ import annotations

from checks_service.enums import CheckKind
from checks_service.exceptions import ApiError, ReceiptNotReadyError
from tests.checks_service.conftest import Bench
from tests.checks_service.factories import PROVERKACHEKA_PAYLOAD, RU_FNS_KEY, RU_FNS_QR

PENDING_URL = "/api/v1/mini-app/pending-checks"


async def test_deferred_check_survives_in_the_list(bench: Bench) -> None:
    """Отложенный при скане чек виден в списке со сводкой из QR."""
    bench.fetcher.fail_with = ReceiptNotReadyError("Касса ещё не передала позиции чека")
    await bench.add(headers=bench.auth())

    response = await bench.client.get(PENDING_URL, headers=bench.auth())

    assert response.status_code == 200
    [item] = response.json()["items"]
    assert item["status"] == "pending"
    assert item["kind"] == "RU_FNS"
    assert item["total"] == "1214.95"
    assert item["purchased_at"].startswith("2026-07-25T15:07")


async def test_manual_retry_saves_the_check(bench: Bench) -> None:
    """Ручной повтор, дождавшийся расшифровки, сохраняет чек без уведомления.

    Уведомление ни к чему: пользователь смотрит на экран. Строку из отложенных
    убирает api вместе с сохранением.
    """
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)

    response = await bench.client.post(f"{PENDING_URL}/{pending.id}/retry", headers=bench.auth())

    assert response.status_code == 201
    [saved] = bench.api.checks.saved
    assert saved["raw_payload"] == PROVERKACHEKA_PAYLOAD
    assert saved["external_key"] == RU_FNS_KEY
    assert saved["notice"] is None
    assert bench.api.pending_checks.failures == []


async def test_failed_manual_retry_keeps_the_check(bench: Bench) -> None:
    """Неудачный ручной повтор — тот же отказ, что при скане, и отчёт в api."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.fetcher.fail_with = ReceiptNotReadyError("Касса ещё не передала позиции чека")

    response = await bench.client.post(f"{PENDING_URL}/{pending.id}/retry", headers=bench.auth())

    assert response.status_code == 409
    assert response.json()["code"] == "receipt_not_ready"
    assert bench.api.pending_checks.failures == [
        {"id": pending.id, "error": "receipt_not_ready", "manual": True}
    ]
    assert bench.api.pending_checks.rows == [pending]


async def test_retry_of_saved_check_forgets_it(bench: Bench) -> None:
    """Чек уже в таблице — отложенный убирается, пользователю «уже добавлен»."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.api.checks.already_saved = True

    response = await bench.client.post(f"{PENDING_URL}/{pending.id}/retry", headers=bench.auth())

    assert response.json()["code"] == "check_already_saved"
    assert bench.api.pending_checks.deleted == [pending.id]


async def test_busy_check_is_not_requested_twice(bench: Bench) -> None:
    """Пока чек спрашивает фон, ручной повтор во внешний сервис не ходит."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.api.pending_checks.busy.add(pending.id)

    response = await bench.client.post(f"{PENDING_URL}/{pending.id}/retry", headers=bench.auth())

    assert response.status_code == 409
    assert response.json()["code"] == "pending_check_busy"
    assert bench.fetcher.calls == []


async def test_delete_removes_the_check(bench: Bench) -> None:
    """Удаление убирает чек; чужой или несуществующий — 404."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    foreign = bench.api.pending_checks.put(8, CheckKind.RU_FNS, RU_FNS_QR)

    assert (
        await bench.client.delete(f"{PENDING_URL}/{pending.id}", headers=bench.auth())
    ).status_code == 204
    assert bench.api.pending_checks.deleted == [pending.id]

    response = await bench.client.delete(f"{PENDING_URL}/{foreign.id}", headers=bench.auth())
    assert response.status_code == 404
    assert response.json()["code"] == "pending_check_not_found"


async def test_pending_endpoints_require_signature(bench: Bench) -> None:
    """Список отложенных без подписи Telegram не отдаётся."""
    assert (await bench.client.get(PENDING_URL)).status_code == 401


async def test_background_pass_saves_with_notice(bench: Bench) -> None:
    """Фон, дождавшийся расшифровки, сохраняет чек со сводкой для уведомления."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.api.pending_checks.due = [pending]

    added = await bench.intake.retry_due()

    assert added == 1
    [saved] = bench.api.checks.saved
    assert saved["spreadsheet_id"] == 7
    assert saved["notice"] == {"total": "1214.95", "purchased_at": "2026-07-25T15:07:00"}


async def test_background_failure_is_reported(bench: Bench) -> None:
    """Неудача фона уходит в api отчётом — паузу и истечение назначает api."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.api.pending_checks.due = [pending]
    bench.fetcher.fail_with = ReceiptNotReadyError("Касса ещё не передала позиции чека")

    assert await bench.intake.retry_due() == 0
    assert bench.api.pending_checks.failures == [
        {"id": pending.id, "error": "receipt_not_ready", "manual": False}
    ]
    assert bench.api.checks.saved == []


async def test_background_forgets_already_saved_check(bench: Bench) -> None:
    """Чек, который тем временем добавили сканом, фон убирает из отложенных."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.api.pending_checks.due = [pending]
    bench.api.checks.already_saved = True

    assert await bench.intake.retry_due() == 0
    assert bench.api.pending_checks.deleted == [pending.id]


async def test_one_broken_check_does_not_stop_the_pass(bench: Bench) -> None:
    """Сбой одного чека не мешает остальным: его вернёт в очередь срок захвата."""
    broken = bench.api.pending_checks.put(7, CheckKind.RU_FNS, "not a receipt")
    good = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.api.pending_checks.due = [broken, good]

    assert await bench.intake.retry_due() == 1
    assert bench.api.pending_checks.failures == [
        {"id": broken.id, "error": "format_not_supported", "manual": False}
    ]


async def test_rejected_save_is_reported_as_a_failure(bench: Bench) -> None:
    """Api не принял чек (документ отвязан) — это неудача, а не вечный повтор."""
    pending = bench.api.pending_checks.put(7, CheckKind.RU_FNS, RU_FNS_QR)
    bench.api.pending_checks.due = [pending]
    bench.api.checks.fail_with = ApiError(404, {"code": "not_found"})

    assert await bench.intake.retry_due() == 0
    assert bench.api.pending_checks.failures == [
        {"id": pending.id, "error": "api_error", "manual": False}
    ]
