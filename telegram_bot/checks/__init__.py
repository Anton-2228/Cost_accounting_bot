"""Разбор сырья чека: `raw_payload` → позиции.

Чистая логика без сети и без aiogram, отдельно от команд — по той же причине,
что и `parsers/`: именно её покрывают тесты таблицей примеров.
"""

from __future__ import annotations

from telegram_bot.checks.errors import (
    ReceiptError,
    ReceiptFormatError,
    ReceiptMismatchError,
    ReceiptNotSupportedError,
)
from telegram_bot.checks.extractor import ReceiptExtractor, RuFnsExtractor, SrbSufExtractor
from telegram_bot.checks.models import Receipt, ReceiptItem, currency_of

__all__ = [
    "Receipt",
    "ReceiptError",
    "ReceiptExtractor",
    "ReceiptFormatError",
    "ReceiptItem",
    "ReceiptMismatchError",
    "ReceiptNotSupportedError",
    "RuFnsExtractor",
    "SrbSufExtractor",
    "currency_of",
]
