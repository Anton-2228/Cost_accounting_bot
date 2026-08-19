"""Клиент модели: подсказки типов товаров и категорий.

Единственный способ, которым бот добирается до LLM. Ни `openai`, ни текстов
промптов за пределами этого пакета нет — ровно как `httpx` не выходит за
пределы `api_client`.
"""

from __future__ import annotations

from telegram_bot.ai.client import AiClient
from telegram_bot.ai.errors import AiError, AiResponseError, AiUnavailableError
from telegram_bot.ai.models import (
    CategorySuggestion,
    CategorySuggestions,
    LlmUsage,
    TypeSuggestion,
    TypeSuggestions,
)

__all__ = [
    "AiClient",
    "AiError",
    "AiResponseError",
    "AiUnavailableError",
    "CategorySuggestion",
    "CategorySuggestions",
    "LlmUsage",
    "TypeSuggestion",
    "TypeSuggestions",
]
