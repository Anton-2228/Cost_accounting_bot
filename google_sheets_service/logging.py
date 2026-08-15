"""Настройка логирования сервиса.

Повторяет :mod:`api.core.logging`: тот же формат строки, чтобы логи двух
контейнеров в одном `docker compose logs` читались как один поток.
"""

from __future__ import annotations

import logging
from logging.config import dictConfig

from google_sheets_service.config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging() -> None:
    """Конфигурирует корневой логгер и логгеры uvicorn единым форматом."""
    level = settings.log_level.upper()
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": _LOG_FORMAT,
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                },
            },
            "root": {
                "level": level,
                "handlers": ["console"],
            },
            "loggers": {
                "uvicorn": {"level": level, "handlers": ["console"], "propagate": False},
                "uvicorn.error": {"level": level, "handlers": ["console"], "propagate": False},
                "uvicorn.access": {"level": level, "handlers": ["console"], "propagate": False},
                # Клиент Google болтлив на уровне INFO и на каждом вызове пишет
                # полный URL с параметрами. В своих логах это шум.
                "googleapiclient": {"level": "WARNING", "handlers": ["console"],
                                    "propagate": False},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    """Возвращает именованный логгер."""
    return logging.getLogger(name)
