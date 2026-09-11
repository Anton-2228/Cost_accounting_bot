"""Response-схема «кто открыл Mini App»."""

from __future__ import annotations

from pydantic import BaseModel


class MeResponse(BaseModel):
    """Кто открыл Mini App и на каком языке с ним говорить.

    `language` — код ISO 639-1 в нижнем регистре: страница выбирает по нему
    свой каталог текстов.
    """

    telegram_id: int
    language: str
