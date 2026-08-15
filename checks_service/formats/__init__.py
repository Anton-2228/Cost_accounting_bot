"""Форматы чеков: парсеры QR-строк и способы получить расшифровку."""

from __future__ import annotations

from checks_service.formats.base import CheckPreview, ParsedCheck, QrParser, ReceiptFetcher
from checks_service.formats.registry import FormatRegistry

__all__ = [
    "CheckPreview",
    "FormatRegistry",
    "ParsedCheck",
    "QrParser",
    "ReceiptFetcher",
]
