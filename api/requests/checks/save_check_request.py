"""Request-схема сохранения чека."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.enums import CheckKind
from api.requests.pending_checks.check_notice_request import CheckNoticeRequest


class SaveCheckRequest(BaseModel):
    """Тело запроса «сохрани расшифрованный чек».

    Приезжает целиком и один раз: расшифровку получает тот, кто сканировал, и
    api записывает готовый результат. Промежуточного состояния «чек добавлен, но
    ещё не расшифрован» в `checks` нет — иначе разбору пришлось бы уметь
    работать с неполными чеками. Чек, который внешний сервис пока не отдал,
    лежит отдельно, в `pending_checks`, и приезжает сюда, когда его получили.

    `raw_payload` кладётся как пришёл: обрезать его здесь значило бы решать за
    будущий разбор, какие поля формата ему понадобятся.
    """

    model_config = ConfigDict(extra="forbid")

    kind: CheckKind
    qr_raw: str = Field(min_length=1)
    external_key: str = Field(min_length=1)
    raw_payload: dict[str, Any]
    fetched_at: datetime
    #: Чек добыт фоновым повтором отложенного — пользователю уходит уведомление
    #: с этой сводкой. Пусто — чек сохраняет тот, кто смотрит на экран.
    notice: CheckNoticeRequest | None = None
