"""Зависимость FastAPI: из заголовка `Authorization` — в telegram_id."""

from __future__ import annotations

from fastapi import Header, Request

from checks_service import constants
from checks_service.auth.init_data import InitDataVerifier
from checks_service.config import settings
from checks_service.exceptions import ForbiddenError, UnauthorizedError


def get_verifier(request: Request) -> InitDataVerifier:
    """Достаёт проверяльщик подписи из состояния приложения."""
    verifier = getattr(request.app.state, "verifier", None)
    if verifier is None:  # pragma: no cover — возможно только при сбое сборки
        raise RuntimeError("Проверка initData не инициализирована в app.state")
    return verifier


def current_telegram_id(
    request: Request,
    authorization: str = Header(default=""),
) -> int:
    """Проверяет `Authorization: tma <initData>` и возвращает telegram_id.

    Списки разрешённых берутся из окружения, а не из api: доступ здесь не
    предметное понятие, а свойство развёртывания — те же списки, что у бота.
    Проверка нужна не ради приватности: расшифровка чека платная и
    лимитированная, и без неё любой, кто узнал адрес Mini App, жёг бы чужой
    лимит.

    Пускается объединение обоих списков. Роль сервис не различает: чеки
    добавляют все одинаково, — но админ, заведённый только в
    `ADMIN_TELEGRAM_IDS`, иначе получал бы здесь отказ, продолжая пользоваться
    ботом.
    """
    scheme, _, init_data = authorization.partition(" ")
    if scheme.lower() != constants.AUTH_SCHEME or not init_data:
        raise UnauthorizedError("Нет данных Telegram в запросе")

    verified = get_verifier(request).verify(init_data)
    if verified.telegram_id not in settings.permitted_telegram_ids:
        raise ForbiddenError("Доступ запрещён")
    return verified.telegram_id
