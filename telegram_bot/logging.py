"""Настройка логирования бота.

Формат строки тот же, что у api и `google_sheets_service`: три сервиса пишут в
один поток `docker compose logs`, и разнобой в формате сделал бы его нечитаемым.
"""

from __future__ import annotations

import logging
from logging.config import dictConfig

from telegram_bot.config import settings

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
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    """Возвращает именованный логгер."""
    return logging.getLogger(name)
