"""Тесты эндпоинтов Mini App.

Стенд (`bench`) собирается в `conftest.py`: приложение поднимается без lifespan
(`ASGITransport` его не выполняет), а состояние собирается руками из фейков —
настоящий граф ходил бы и в api, и во внешний сервис расшифровки.
"""

from __future__ import annotations

import httpx

from checks_service.exceptions import (
    ApiError,
    ReceiptFetchError,
    ReceiptNotFoundError,
    ReceiptNotReadyError,
)
from tests.checks_service.conftest import ALLOWED_ID, ME_URL, STRANGER_ID, Bench
from tests.checks_service.factories import PROVERKACHEKA_PAYLOAD, RU_FNS_KEY, RU_FNS_QR


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


async def test_receipt_not_ready_saves_nothing(bench: Bench) -> None:
    """Чек, который касса ещё не передала, не кладётся в очередь пустышкой.

    Свой код нужен странице: на нём она оставляет карточку и предлагает
    повторить, а не сканировать чек у кассы заново.
    """
    bench.fetcher.fail_with = ReceiptNotReadyError("Касса ещё не передала позиции чека")

    response = await bench.add(headers=bench.auth())

    assert response.status_code == 409
    assert response.json()["code"] == "receipt_not_ready"
    assert bench.api.checks.saved == []


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


async def test_me_names_the_language_chosen_in_the_bot(bench: Bench) -> None:
    """Страница говорит на языке, выбранном в боте, а не на языке клиента."""
    bench.api.users.language_code = "es"

    response = await bench.client.get(ME_URL, headers=bench.auth())

    assert response.status_code == 200
    assert response.json() == {"telegram_id": ALLOWED_ID, "language": "es"}


async def test_me_for_unknown_user_is_english(bench: Bench) -> None:
    """Незнакомый api пользователь — английский, как и в боте."""
    response = await bench.client.get(ME_URL, headers=bench.auth())

    assert response.json()["language"] == "en"


async def test_me_with_unavailable_api_is_502(bench: Bench) -> None:
    """Недоступное api — 502 с кодом: страница уйдёт на запасной язык."""
    bench.api.users.fail_with = ApiError(503, "api лежит")

    response = await bench.client.get(ME_URL, headers=bench.auth())

    assert response.status_code == 502
    assert response.json()["code"] == "api_error"


async def test_me_requires_a_signature(bench: Bench) -> None:
    """Язык чужого пользователя без подписи не отдаётся."""
    response = await bench.client.get(ME_URL)

    assert response.status_code == 401
    assert bench.api.users.calls == []


async def test_me_refuses_a_stranger(bench: Bench) -> None:
    """Подпись верна, но пользоваться сервисом нельзя — 403, api не спрашивали."""
    response = await bench.client.get(ME_URL, headers=bench.auth(STRANGER_ID))

    assert response.status_code == 403
    assert bench.api.users.calls == []
