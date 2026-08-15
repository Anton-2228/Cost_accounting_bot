"""Request-схема отчёта об успешной перерисовке."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompleteTaskRequest(BaseModel):
    """Тело отчёта «лист перерисован».

    `requested_at` — то самое значение, которое пришло вместе с задачей. Оно
    играет роль версии: если за время работы лист изменили снова, значение уже
    другое, задача остаётся в очереди и будет выполнена ещё раз.
    """

    model_config = ConfigDict(extra="forbid")

    requested_at: datetime
