"""Общие конверты ответов."""

from __future__ import annotations

from api.responses.common.data_response import DataResponse
from api.responses.common.error_response import ErrorResponse
from api.responses.common.items_response import ItemsResponse
from api.responses.common.page import Page

__all__ = ["DataResponse", "ErrorResponse", "ItemsResponse", "Page"]
