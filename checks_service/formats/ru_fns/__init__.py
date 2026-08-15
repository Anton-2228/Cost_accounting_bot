"""Российский фискальный чек: QR-код ФНС и расшифровка через proverkacheka.com."""

from __future__ import annotations

from checks_service.formats.ru_fns.fetcher import ProverkachekaFetcher
from checks_service.formats.ru_fns.parser import RuFnsQrParser

__all__ = ["ProverkachekaFetcher", "RuFnsQrParser"]
