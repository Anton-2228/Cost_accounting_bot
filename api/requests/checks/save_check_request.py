"""Request-схема сохранения чека."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.enums import CheckKind


class SaveCheckRequest(BaseModel):
    """Тело запроса «сохрани расшифрованный чек».

    Приезжает целиком и один раз: расшифровку получает тот, кто сканировал, и
    api записывает готовый результат. Промежуточного состояния «чек добавлен, но
    ещё не расшифрован» нет — оно потребовало бы фонового дозабора и обработки
    неполных чеков на разборе.

    `raw_payload` кладётся как пришёл: обрезать его здесь значило бы решать за
    будущий разбор, какие поля формата ему понадобятся.
    """

    model_config = ConfigDict(extra="forbid")

    kind: CheckKind
    qr_raw: str = Field(min_length=1)
    external_key: str = Field(min_length=1)
    raw_payload: dict[str, Any]
    fetched_at: datetime
