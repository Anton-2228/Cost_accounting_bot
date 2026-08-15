"""Request-схема перевода между счетами."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.core import constants
from api.core.types import PositiveMoneyDecimal


class CreateTransferRequest(BaseModel):
    """Тело запроса перевода.

    Совпадение счетов проверяет сервис, а не схема: это правило предметной
    области (422 с кодом), а не формат запроса.
    """

    model_config = ConfigDict(extra="forbid")

    from_source_id: int = Field(gt=0)
    to_source_id: int = Field(gt=0)
    amount: PositiveMoneyDecimal
    notes: str = Field(default="", max_length=constants.NOTES_MAX_LENGTH)
