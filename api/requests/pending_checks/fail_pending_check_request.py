"""Request-схема отчёта о неудачной попытке получить отложенный чек."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from api.requests.pending_checks.check_notice_request import CheckNoticeRequest


class FailPendingCheckRequest(BaseModel):
    """Тело отчёта «чек снова не получен»."""

    model_config = ConfigDict(extra="forbid")

    #: Машинный код отказа (`receipt_not_ready`, …).
    error: str = Field(min_length=1)
    #: Попытку сделал пользователь, а не фон: окно попыток открывается заново.
    manual: bool = False
    #: Сводка на случай, если на этой неудаче окно истечёт и уйдёт уведомление.
    #: Пусто — назвать чек нечем, и об истечении пользователь узнает из Mini App.
    notice: CheckNoticeRequest | None = None
