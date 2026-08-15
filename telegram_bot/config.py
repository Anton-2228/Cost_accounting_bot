"""Конфигурация бота на основе pydantic-settings.

Принцип разделения тот же, что в :mod:`api.core.config`: параметры
развёртывания (токен, адрес api, Redis) — обязательные поля без значений по
умолчанию, поведенческие дефолты живут в :mod:`telegram_bot.constants`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from telegram_bot import constants


class Settings(BaseSettings):
    """Настройки telegram-бота."""

    model_config = SettingsConfigDict(
        env_file="env/telegram_bot.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Развёртывание: только из окружения, без дефолтов в коде ----
    telegram_bot_token: str
    api_base_url: str
    redis_host: str

    # ---- Поведение ----
    redis_port: int = constants.DEFAULT_REDIS_PORT
    redis_db: int = 0
    redis_password: str | None = None

    api_timeout_seconds: float = constants.DEFAULT_API_TIMEOUT_SECONDS
    notify_port: int = constants.DEFAULT_NOTIFY_PORT

    # Список telegram_id, которым разрешено пользоваться ботом. Пустой список
    # означает «никому»: бот заводит документы в Google на общий сервисный
    # аккаунт, квота которого одна на проект, поэтому открытый по умолчанию
    # доступ был бы способом её исчерпать чужими руками.
    allowed_telegram_ids: Annotated[frozenset[int], NoDecode] = frozenset()

    app_name: str = "Cost Accounting Telegram Bot"
    log_level: str = "INFO"

    @field_validator("allowed_telegram_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        """Принимает список id строкой через запятую.

        `NoDecode` в аннотации обязателен: без него pydantic-settings пробует
        разобрать значение как JSON **до** валидатора, и `ALLOWED_TELEGRAM_IDS=1,2`
        валит процесс на старте ошибкой разбора JSON — для настройки в одну
        строку это выглядело бы загадкой.
        """
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def redis_url(self) -> str:
        """DSN хранилища состояний aiogram."""
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр настроек."""
    return Settings()  # значения берутся из окружения


settings = get_settings()
