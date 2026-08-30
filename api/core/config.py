"""Конфигурация приложения на основе pydantic-settings.

Принцип разделения значений:

* Параметры развёртывания (Postgres) — ОБЯЗАТЕЛЬНЫЕ поля без значений по
  умолчанию. Единственный источник — окружение (`env/api.env`), шаблон —
  `env/api.env.example`. Отсутствие переменной валит процесс на старте, а не
  посреди запроса.
* Поведенческие дефолты берутся из :mod:`api.core.constants` и здесь не
  дублируются «магическими» литералами.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from api.core import constants


class Settings(BaseSettings):
    """Настройки приложения, читаются из окружения и `env/api.env`."""

    model_config = SettingsConfigDict(
        env_file="env/api.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Развёртывание: только из окружения, без дефолтов в коде ----
    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str

    # ---- Поведение: дефолты живут в constants ----
    app_name: str = "Cost Accounting API"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    default_page_limit: int = constants.DEFAULT_PAGE_LIMIT
    max_page_limit: int = constants.MAX_PAGE_LIMIT

    # Адрес, по которому бот принимает уведомления. Пустое значение выключает
    # рассылку целиком: api должен запускаться и без бота — в тестах, в
    # одиночном прогоне и пока бот не развёрнут.
    bot_notify_url: str | None = None
    notification_push_interval_seconds: int = constants.NOTIFICATION_PUSH_INTERVAL_SECONDS
    notification_push_timeout_seconds: float = constants.NOTIFICATION_PUSH_TIMEOUT_SECONDS

    # Источник курсов валют. Ключа нет и не предполагается: выбранная раздача —
    # статические файлы на CDN. Второй адрес независим от первого и служит
    # запасным, а не заменой: оба раздают одни и те же данные.
    currency_api_base_url: str = constants.CURRENCY_API_BASE_URL
    currency_api_fallback_url_template: str = constants.CURRENCY_API_FALLBACK_URL_TEMPLATE
    currency_api_timeout_seconds: float = constants.CURRENCY_API_TIMEOUT_SECONDS

    @property
    def database_url(self) -> str:
        """Async-DSN для приложения (asyncpg)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр настроек."""
    return Settings()  # значения берутся из окружения


settings = get_settings()
