"""Обобщённый конверт для списка."""

from __future__ import annotations

from pydantic import BaseModel


class ItemsResponse[T](BaseModel):
    """Список без пагинации.

    Отдельный конверт, а не :class:`api.responses.common.page.Page`, потому что
    пагинировать здесь нечего: каждая выборка ограничена одним документом и
    одним учётным месяцем. Отдавать `limit`/`offset`/`total`, которые никогда не
    меняются, значило бы обещать клиенту постраничность, которой нет.
    """

    items: list[T]
