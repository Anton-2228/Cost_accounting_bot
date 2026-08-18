"""Доменная модель сохранённого чека."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from api.enums import CheckKind


class Check(BaseModel):
    """Сырьё чека: QR-строка, вид формата и расшифровка целиком.

    Разбором чека (типы товаров, категории, операции) занимается бот, и до него
    ни одно поле `raw_payload` не интерпретируется. Поэтому здесь нет ни суммы,
    ни даты: у каждого формата они лежат по-своему, и вытащить их наверх значило
    бы зашить один формат в общую модель.

    `processed_at` — метка разбора: пусто, значит чек ждёт своей очереди.
    `deleted_at` — метка мягкого удаления: чек умирает вслед за последней своей
    живой операцией, а сырьё покупки остаётся.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    spreadsheet_id: int
    kind: CheckKind
    qr_raw: str
    external_key: str
    raw_payload: dict[str, Any]
    fetched_at: datetime
    processed_at: datetime | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
