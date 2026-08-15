"""Конфигурация сервиса на основе pydantic-settings.

Принцип разделения тот же, что в :mod:`api.core.config`: параметры развёртывания
приходят только из окружения, поведенческие дефолты — из
:mod:`google_sheets_service.constants` и отсюда же, но без «магических» литералов
по коду.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class GoogleSheetsServiceSettings(BaseSettings):
    """Настройки сервиса синхронизации с Google Sheets.

    Учётные данные сервисного аккаунта задаются ОДНИМ из двух способов:
    `google_credentials_json` — сам JSON-ключ в переменной окружения, или
    `google_credentials_path` — путь к смонтированному файлу. Если заданы оба,
    выигрывает inline-JSON.
    """

    model_config = SettingsConfigDict(
        env_file="env/google_sheets_service.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Основное api ----
    api_base_url: str = "http://api:8000/api/v1"
    api_timeout_seconds: float = 30.0

    # ---- Google ----
    google_credentials_json: str | None = None
    google_credentials_path: str | None = None
    # Явный socket-таймаут. Без него googleapiclient ставит неявную минуту, и на
    # протухшем keep-alive соединении тик висит всю её до «read operation timed
    # out».
    google_timeout_seconds: float = 20.0
    google_max_retries: int = 5
    google_retry_base_seconds: float = 1.0
    google_retry_jitter_seconds: float = 0.3

    # ---- Цикл ----
    #: Сколько задач забирается за один тик.
    claim_limit: int = 20
    #: Пауза МЕЖДУ задачами: размазывает нагрузку под квоту Google (60 запросов
    #: в минуту на проект). Она же — нижняя граница пустого тика, чтобы цикл не
    #: крутил `claim` вплотную, когда очередь пуста.
    tick_interval_seconds: float = 5.0
    tick_jitter_seconds: float = 1.0
    #: Задержка первого прохода: api и Postgres поднимаются не мгновенно.
    initial_delay_seconds: float = 5.0

    # ---- Прочее ----
    app_name: str = "Cost Accounting Google Sheets Service"
    debug: bool = False
    log_level: str = "INFO"


@lru_cache
def get_settings() -> GoogleSheetsServiceSettings:
    """Возвращает кэшированный экземпляр настроек."""
    return GoogleSheetsServiceSettings()  # значения берутся из окружения


settings = get_settings()
