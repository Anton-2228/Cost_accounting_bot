"""Проверка права пользоваться ботом."""

from __future__ import annotations

from collections.abc import Iterable

ACCESS_DENIED_MESSAGE = "Доступ запрещён"


class AccessGuard:
    """Пускает только известные telegram_id.

    Список задаётся окружением бота, а не таблицей в api: доступ здесь — не
    предметное понятие, а свойство развёртывания. Проверка нужна потому, что
    `/start` заводит документ в Google на общий сервисный аккаунт с квотой в 60
    запросов в минуту **на весь проект**: без списка любой прохожий мог бы её
    израсходовать, и перестали бы обновляться чужие таблицы.

    Пустой список означает «никому»: бот, случайно поднятый без настройки, не
    должен оказаться открытым.
    """

    def __init__(self, allowed_telegram_ids: Iterable[int]) -> None:
        self._allowed = frozenset(allowed_telegram_ids)

    def is_allowed(self, telegram_id: int | None) -> bool:
        """Разрешено ли этому пользователю обращаться к боту."""
        if telegram_id is None:
            return False
        return telegram_id in self._allowed
