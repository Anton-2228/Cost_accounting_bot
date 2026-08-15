"""Response-схема добавленного чека."""

from __future__ import annotations

from pydantic import BaseModel

from checks_service.enums import CheckKind
from checks_service.services.check_intake import Intake


class SavedCheckResponse(BaseModel):
    """Чек добавлен: его идентификатор в api и вид формата.

    Расшифровку наружу не отдаём: страница её не показывает, а весит она
    десятки килобайт — разбор возьмёт её из БД, когда до него дойдёт очередь.
    """

    id: int
    kind: CheckKind

    @classmethod
    def of(cls, intake: Intake) -> SavedCheckResponse:
        """Собирает ответ из результата добавления."""
        return cls(id=intake.saved.id, kind=intake.parsed.kind)
