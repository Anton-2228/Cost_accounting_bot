"""Клиент сайдкара qr_vision: чтение QR с фото моделью, когда zxing не справился."""

from __future__ import annotations

from checks_service.qr_vision.client import QrVisionClient, QrVisionResult, QrVisionUsage

__all__ = ["QrVisionClient", "QrVisionResult", "QrVisionUsage"]
