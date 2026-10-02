"""Response-схема «QR-строка с фотографии»."""

from __future__ import annotations

from pydantic import BaseModel


class DecodedPhotoResponse(BaseModel):
    """Строка QR-кода, найденная на фотографии чека.

    Страница отправляет её дальше ровно как строку из сканера: на плашку, а
    после подтверждения — на добавление.
    """

    qr_raw: str
