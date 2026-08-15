"""Разбор и проверка `initData` Telegram Mini App.

`initData` — это query-строка, которую Telegram отдаёт странице внутри клиента.
Она подписана токеном бота, и подпись — единственное, что отличает настоящего
пользователя от кого угодно, открывшего адрес Mini App в обычном браузере.
Сервис не имеет собственных сессий и cookie: подпись приезжает с каждым
запросом.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl

from pydantic import BaseModel

from checks_service import constants
from checks_service.exceptions import UnauthorizedError


class InitData(BaseModel):
    """Проверенные данные Mini App: кто открыл страницу и когда."""

    telegram_id: int
    auth_date: datetime


class InitDataVerifier:
    """Проверяет подпись и свежесть `initData`.

    Две проверки, и обе обязательны. Подпись отвечает на вопрос «эту строку
    выдал Telegram нашему боту?», но действует бессрочно: без ограничения
    возраста однажды перехваченная строка открывала бы доступ навсегда.
    """

    def __init__(self, bot_token: str, *, max_age_seconds: int) -> None:
        # Секрет выводится из токена один раз: он не зависит ни от запроса, ни
        # от пользователя.
        self._secret = hmac.new(
            constants.INIT_DATA_SECRET_KEY,
            bot_token.encode(),
            hashlib.sha256,
        ).digest()
        self._max_age_seconds = max_age_seconds

    def verify(self, init_data: str, *, now: datetime | None = None) -> InitData:
        """Проверяет строку и возвращает пользователя; иначе бросает 401."""
        pairs = parse_qsl(init_data, keep_blank_values=True)
        if not pairs:
            raise UnauthorizedError("Данные Telegram отсутствуют")

        fields = dict(pairs)
        received_hash = fields.pop(constants.INIT_DATA_HASH_FIELD, None)
        if not received_hash:
            raise UnauthorizedError("Подпись Telegram отсутствует")

        if not hmac.compare_digest(self._sign(fields), received_hash):
            raise UnauthorizedError("Подпись Telegram не сошлась")

        auth_date = self._auth_date(fields)
        moment = now if now is not None else datetime.now(UTC)
        if (moment - auth_date).total_seconds() > self._max_age_seconds:
            raise UnauthorizedError("Данные Telegram устарели, откройте приложение заново")

        return InitData(telegram_id=self._telegram_id(fields), auth_date=auth_date)

    def _sign(self, fields: dict[str, str]) -> str:
        """Считает подпись по всем полям, кроме самой подписи.

        Поля сортируются по имени и склеиваются через перевод строки — ровно
        так, как это описано у Telegram. Сортировка существенна: порядок полей
        в query-строке не гарантирован, и подпись по «как пришло» разошлась бы
        на первом же клиенте, который переставит их местами.
        """
        payload = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
        return hmac.new(self._secret, payload.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _auth_date(fields: dict[str, str]) -> datetime:
        """Достаёт время выдачи (unix-время в UTC)."""
        raw = fields.get(constants.INIT_DATA_AUTH_DATE_FIELD)
        if raw is None:
            raise UnauthorizedError("В данных Telegram нет времени выдачи")
        try:
            return datetime.fromtimestamp(int(raw), tz=UTC)
        except (ValueError, OverflowError, OSError) as error:
            raise UnauthorizedError("Некорректное время выдачи в данных Telegram") from error

    @staticmethod
    def _telegram_id(fields: dict[str, str]) -> int:
        """Достаёт идентификатор пользователя из поля `user`.

        Поле приезжает JSON-строкой. Разбирать его можно только **после**
        проверки подписи: до неё это произвольный текст от кого угодно.
        """
        raw = fields.get(constants.INIT_DATA_USER_FIELD)
        if raw is None:
            raise UnauthorizedError("В данных Telegram нет пользователя")
        try:
            user: Any = json.loads(raw)
            return int(user["id"])
        except (ValueError, TypeError, KeyError) as error:
            raise UnauthorizedError("Некорректный пользователь в данных Telegram") from error
