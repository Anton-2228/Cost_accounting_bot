"""Тесты договора бота с api о доставке уведомлений.

Предмет проверки — код ответа, а не текст сообщения. Он решает судьбу строки в
очереди: 204 снимает её навсегда, 503 оставляет на повтор. Ошибка в этой
границе не видна ни в одном другом тесте, зато видна в журнале — одним и тем же
стектрейсом каждые пятнадцать секунд.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.methods import SendMessage
from fastapi import status
from fastapi.testclient import TestClient

from telegram_bot.notify_server import NotifyServer

_PAYLOAD = {
    "notification_id": 1,
    "telegram_id": 777,
    "kind": "TABLE_READY",
    "text": "Таблица готова",
}


class _FakeWrapper:
    """Подмена обёртки aiogram: помнит вызовы и падает по сценарию."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> Any:
        """Повторяет форму настоящего метода."""
        self.sent.append((chat_id, text))
        if self._error is not None:
            raise self._error
        return None


class _FakeMenu:
    """Подмена экрана меню: помнит, кому его нарисовали, и падает по сценарию."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.shown: list[int] = []

    async def show(self, *, chat_id: int) -> None:
        """Повторяет форму настоящего метода."""
        self.shown.append(chat_id)
        if self._error is not None:
            raise self._error


def _client(
    error: Exception | None = None,
    menu_error: Exception | None = None,
) -> tuple[TestClient, _FakeWrapper, _FakeMenu]:
    """Клиент поверх notify-сервера с подменёнными обёрткой и меню."""
    wrapper = _FakeWrapper(error)
    menu = _FakeMenu(menu_error)
    server = NotifyServer(wrapper, menu)  # type: ignore[arg-type]
    return TestClient(server.build_app()), wrapper, menu


def _method() -> SendMessage:
    """Метод Telegram, который нужен исключениям aiogram для конструктора."""
    return SendMessage(chat_id=777, text="Таблица готова")


def test_delivered_message_is_confirmed() -> None:
    """Успешная отправка подтверждается 204 — api ставит delivered_at."""
    client, wrapper, menu = _client()

    response = client.post("/notify", json=_PAYLOAD)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert wrapper.sent == [(777, "Таблица готова")]
    assert menu.shown == [777]


def test_other_kinds_do_not_draw_the_menu() -> None:
    """Меню появляется по готовности таблицы, а не после любого уведомления.

    Ролловер и разбор листа приходят к владельцу давно готовой таблицы: экран
    после каждого из них был бы не подсказкой, а помехой.
    """
    client, _, menu = _client()

    response = client.post("/notify", json={**_PAYLOAD, "kind": "ROLLOVER"})

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert menu.shown == []


def test_unknown_kind_is_still_delivered() -> None:
    """Незнакомый вид уведомления печатается, а не роняет доставку.

    Перечисление видов — зеркало api, и отстать оно может на одну выкладку.
    Пока это так, текст важнее вида: печатать бот умеет любой.
    """
    client, wrapper, menu = _client()

    response = client.post("/notify", json={**_PAYLOAD, "kind": "СОВСЕМ_НОВОЕ"})

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert wrapper.sent == [(777, "Таблица готова")]
    assert menu.shown == []


def test_broken_menu_does_not_resend_the_notification() -> None:
    """Ошибка отрисовки меню не превращает 204 в 503.

    Текст уже доставлен. Ответив 503, бот попросил бы api прислать его второй
    раз, и пользователь получил бы «таблица готова» дважды — из-за экрана,
    который к самой доставке отношения не имеет.
    """
    client, wrapper, menu = _client(menu_error=RuntimeError("меню не нарисовалось"))

    response = client.post("/notify", json=_PAYLOAD)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert wrapper.sent == [(777, "Таблица готова")]
    assert menu.shown == [777]


@pytest.mark.parametrize(
    "error",
    [
        TelegramForbiddenError(method=_method(), message="bot was blocked by the user"),
        TelegramBadRequest(method=_method(), message="chat not found"),
    ],
    ids=["заблокировал бота", "чат не найден"],
)
def test_permanent_failure_is_confirmed_anyway(error: Exception) -> None:
    """Неисправимый отказ снимает уведомление с очереди.

    «chat not found» означает, что пользователь ни разу не писал боту: начать
    диалог первым бот не может, и повтор ничего не изменит. Отвечать здесь 503
    значит навсегда заклинить очередь этого пользователя и залить журнал
    одинаковыми стектрейсами.
    """
    client, _, _menu = _client(error)

    response = client.post("/notify", json=_PAYLOAD)

    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.parametrize(
    "error",
    [
        TelegramRetryAfter(method=_method(), message="Too Many Requests", retry_after=30),
        TelegramNetworkError(method=_method(), message="connection reset"),
        RuntimeError("что-то неожиданное"),
    ],
    ids=["просят подождать", "сетевой сбой", "неизвестная ошибка"],
)
def test_temporary_failure_keeps_the_notification(error: Exception) -> None:
    """Временная неудача оставляет уведомление в очереди."""
    client, _, _menu = _client(error)

    response = client.post("/notify", json=_PAYLOAD)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_unknown_field_is_rejected() -> None:
    """Лишнее поле в теле — ошибка схемы, а не молчаливое игнорирование."""
    client, _, _menu = _client()

    response = client.post("/notify", json={**_PAYLOAD, "surprise": 1})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_health() -> None:
    """Healthcheck контейнера отвечает."""
    client, _, _menu = _client()
    assert client.get("/health").status_code == status.HTTP_200_OK
