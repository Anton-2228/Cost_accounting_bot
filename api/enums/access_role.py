"""Роль доступа к Google-документу."""

from __future__ import annotations

from enum import StrEnum


class AccessRole(StrEnum):
    """Права, выдаваемые почте на документ (терминология Google Drive)."""

    READER = "READER"
    WRITER = "WRITER"
