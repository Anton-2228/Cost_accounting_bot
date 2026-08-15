"""Request-схема отсканированного QR-кода."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Разумный потолок длины. QR-код фискального чека укладывается в сотню
#: символов; всё, что сильно длиннее, — не чек, и разбирать это незачем.
QR_MAX_LENGTH = 1024


class ScanRequest(BaseModel):
    """Тело запроса «вот что отсканировал пользователь».

    Одна и та же схема у `preview` и у сохранения: сервис не держит состояния
    между запросами, поэтому строка приезжает оба раза целиком и оба раза
    разбирается заново. Иначе клиент мог бы подменить реквизиты между показом
    плашки и записью.
    """

    model_config = ConfigDict(extra="forbid")

    qr_raw: str = Field(min_length=1, max_length=QR_MAX_LENGTH)
