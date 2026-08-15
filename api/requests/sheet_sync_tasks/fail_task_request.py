"""Request-схема отчёта о неудачной перерисовке."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FailTaskRequest(BaseModel):
    """Тело отчёта «перерисовать не удалось»."""

    model_config = ConfigDict(extra="forbid")

    error: str = Field(min_length=1)
    #: Повтор заведомо получит тот же ответ: файл удалён, доступ отозван, лист не
    #: найден. Отличать это от «Google моргнул» умеет только вызывающий — он
    #: видит код ответа Google, а api никаких внешних вызовов не делает.
    terminal: bool = False
