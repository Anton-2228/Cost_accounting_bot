"""Сборка русских сообщений из данных api.

Чистая логика без сети и aiogram: формулировки проверяются тестами, а не
глазами в переписке с ботом.
"""

from __future__ import annotations

from telegram_bot.formatting.check_formatter import CheckFormatter
from telegram_bot.formatting.llm_usage_formatter import LlmUsageFormatter, SpreadsheetUsage
from telegram_bot.formatting.money_formatter import MoneyFormatter
from telegram_bot.formatting.record_formatter import RecordFormatter
from telegram_bot.formatting.table_formatter import TableFormatter
from telegram_bot.formatting.transfer_formatter import TransferFormatter

__all__ = [
    "CheckFormatter",
    "LlmUsageFormatter",
    "MoneyFormatter",
    "RecordFormatter",
    "SpreadsheetUsage",
    "TableFormatter",
    "TransferFormatter",
]
