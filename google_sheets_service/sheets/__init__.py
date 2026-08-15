"""Описание листов и сборка тел запросов к Google Sheets.

Весь пакет — чистые функции: доменные данные на входе, тела запросов на выходе.
Чтение делает движок, поэтому одна выборка обслуживает целый лист.
"""

from __future__ import annotations

from google_sheets_service.sheets.layout import Column, SheetLayout, SheetPayload
from google_sheets_service.sheets.layouts import (
    BILLS_LAYOUT,
    CATEGORIES_LAYOUT,
    OPERATIONS_LAYOUT,
    operations_sheet_title,
    period_days,
    statistics_layout,
    statistics_sheet_title,
)

__all__ = [
    "BILLS_LAYOUT",
    "CATEGORIES_LAYOUT",
    "OPERATIONS_LAYOUT",
    "Column",
    "SheetLayout",
    "SheetPayload",
    "operations_sheet_title",
    "period_days",
    "statistics_layout",
    "statistics_sheet_title",
]
