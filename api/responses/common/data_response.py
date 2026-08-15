"""Конверт ответа для одиночного ресурса."""

from __future__ import annotations

from pydantic import BaseModel


class DataResponse[T](BaseModel):
    """Единый конверт ответа для одиночного ресурса."""

    data: T
