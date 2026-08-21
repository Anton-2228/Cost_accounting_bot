"""Конфигурация сервиса на основе pydantic-settings.

Принцип разделения тот же, что в :mod:`api.core.config`: параметры
развёртывания (токен бота, адреса, ключ внешнего сервиса) приходят только из
окружения, поведенческие дефолты — из :mod:`checks_service.constants` и отсюда.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class ChecksServiceSettings(BaseSettings):
    """Настройки сервиса добавления чеков."""

    model_config = SettingsConfigDict(
        env_file="env/checks_service.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Развёртывание: только из окружения, без дефолтов в коде ----
    #: Тем же токеном Telegram подписывает `initData`, поэтому он здесь не для
    #: отправки сообщений (сервис их не шлёт), а для проверки подписи.
    telegram_bot_token: str

    # ---- Основное api ----
    api_base_url: str = "http://api:8000/api/v1"
    api_timeout_seconds: float = 30.0

    # ---- Внешняя расшифровка чеков (Россия, ФНС) ----
    proverkacheka_base_url: str = "https://proverkacheka.com/api/v1/check/get"
    proverkacheka_api_token: str = ""
    #: Явный таймаут. Старая версия звала `requests.post` без таймаута прямо из
    #: асинхронного кода, и зависший proverkacheka останавливал весь бот.
    proverkacheka_timeout_seconds: float = 20.0

    # ---- Доступ ----
    #: Кому разрешено добавлять чеки: тот же список, что у бота. Проверка нужна
    #: не ради приватности — расшифровка чека платная и лимитированная, и без
    #: списка любой, кто узнал адрес Mini App, жёг бы чужой лимит.
    #: Пустой список означает «никому»: сервис, случайно поднятый без
    #: настройки, не должен оказаться открытым.
    allowed_telegram_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    #: Админы — тот же список, что у бота. Сервис не различает роли: чеки
    #: добавляют все одинаково. Список нужен затем, что доступ считается
    #: объединением, и без него админ, заведённый только в `ADMIN_TELEGRAM_IDS`,
    #: пользовался бы ботом, но получал отказ в Mini App.
    admin_telegram_ids: Annotated[frozenset[int], NoDecode] = frozenset()
    #: Возраст `initData`, после которого она считается протухшей. Подпись
    #: бессрочна сама по себе, поэтому без ограничения перехваченная строка
    #: работала бы вечно.
    init_data_max_age_seconds: int = 24 * 60 * 60

    # ---- Прочее ----
    app_name: str = "Cost Accounting Checks Service"
    debug: bool = False
    log_level: str = "INFO"

    @property
    def permitted_telegram_ids(self) -> frozenset[int]:
        """Все, кому разрешено добавлять чеки: пользователи и админы."""
        return self.allowed_telegram_ids | self.admin_telegram_ids

    @field_validator("allowed_telegram_ids", "admin_telegram_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        """Принимает список id строкой через запятую.

        `NoDecode` в аннотации обязателен: без него pydantic-settings пробует
        разобрать значение как JSON **до** валидатора, и `ALLOWED_TELEGRAM_IDS=1,2`
        валит процесс на старте ошибкой разбора JSON.
        """
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> ChecksServiceSettings:
    """Возвращает кэшированный экземпляр настроек."""
    return ChecksServiceSettings()  # значения берутся из окружения


settings = get_settings()
