"""Тесты проверки подписи `initData`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from checks_service.auth.init_data import InitDataVerifier
from checks_service.exceptions import UnauthorizedError
from tests.checks_service.conftest import ALLOWED_ID, BOT_TOKEN
from tests.checks_service.factories import make_init_data

MAX_AGE = 3600


def _verifier(token: str = BOT_TOKEN) -> InitDataVerifier:
    """Проверяльщик с часовым сроком годности."""
    return InitDataVerifier(token, max_age_seconds=MAX_AGE)


def test_valid_init_data_yields_user() -> None:
    """Правильно подписанная строка отдаёт того, кто открыл приложение."""
    verified = _verifier().verify(make_init_data(telegram_id=ALLOWED_ID, bot_token=BOT_TOKEN))
    assert verified.telegram_id == ALLOWED_ID


def test_tampered_user_breaks_signature() -> None:
    """Подменённый после подписи пользователь не проходит.

    Ровно это и защищает сервис: без проверки чужой telegram_id открывал бы
    доступ к чужой таблице.
    """
    with pytest.raises(UnauthorizedError):
        _verifier().verify(
            make_init_data(telegram_id=ALLOWED_ID, bot_token=BOT_TOKEN, tamper=True)
        )


def test_signature_of_another_bot_is_rejected() -> None:
    """Строка, подписанная чужим токеном, не проходит."""
    alien = make_init_data(telegram_id=ALLOWED_ID, bot_token="999999:OTHER-BOT-TOKEN")
    with pytest.raises(UnauthorizedError):
        _verifier().verify(alien)


def test_expired_init_data_is_rejected() -> None:
    """Протухшая строка не проходит, хотя подпись у неё верная.

    Подпись бессрочна, поэтому без ограничения возраста однажды перехваченная
    строка работала бы вечно.
    """
    old = datetime.now(UTC) - timedelta(seconds=MAX_AGE + 60)
    with pytest.raises(UnauthorizedError):
        _verifier().verify(
            make_init_data(telegram_id=ALLOWED_ID, bot_token=BOT_TOKEN, auth_date=old)
        )


def test_fresh_init_data_at_the_edge_of_the_window_passes() -> None:
    """Граница окна не отсекает вчера выданную и ещё живую строку."""
    edge = datetime.now(UTC) - timedelta(seconds=MAX_AGE - 60)
    verified = _verifier().verify(
        make_init_data(telegram_id=ALLOWED_ID, bot_token=BOT_TOKEN, auth_date=edge)
    )
    assert verified.telegram_id == ALLOWED_ID


@pytest.mark.parametrize(
    "init_data",
    ["", "auth_date=1&user=%7B%22id%22%3A1%7D", "hash=deadbeef"],
    ids=["пусто", "без подписи", "без полей"],
)
def test_malformed_init_data_is_rejected(init_data: str) -> None:
    """Строка без подписи или без полей — 401, а не пятисотка."""
    with pytest.raises(UnauthorizedError):
        _verifier().verify(init_data)
