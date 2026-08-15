"""Вид категории: доход или расход."""

from __future__ import annotations

from enum import StrEnum


class CategoryKind(StrEnum):
    """Определяет знак операции: доход прибавляется к балансу, расход вычитается."""

    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
