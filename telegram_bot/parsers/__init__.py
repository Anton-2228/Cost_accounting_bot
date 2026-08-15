"""Разбор пользовательского ввода.

Чистая логика без обращений к сети и к aiogram — поэтому она и вынесена
отдельно от команд: именно её покрывают тесты.
"""

from __future__ import annotations

from telegram_bot.parsers.amount_parser import AmountParser
from telegram_bot.parsers.association_matcher import AssociationMatcher
from telegram_bot.parsers.onboarding_parser import OnboardingParser
from telegram_bot.parsers.record_parser import RecordParser
from telegram_bot.parsers.results import ParsedRecord, ParsedTransfer, ParseError
from telegram_bot.parsers.transfer_parser import TransferParser

__all__ = [
    "AmountParser",
    "AssociationMatcher",
    "OnboardingParser",
    "ParseError",
    "ParsedRecord",
    "ParsedTransfer",
    "RecordParser",
    "TransferParser",
]
