"""Проверка права пользоваться ботом и роли обратившегося."""

from __future__ import annotations

from collections.abc import Iterable

ACCESS_DENIED_MESSAGE = "Доступ запрещён"


class AccessGuard:
    """Пускает только известные telegram_id и отличает админа от пользователя.

    Списки задаются окружением бота, а не таблицей в api: доступ здесь — не
    предметное понятие, а свойство развёртывания. Проверка нужна потому, что
    `/start` заводит документ в Google на общий сервисный аккаунт с квотой в 60
    запросов в минуту **на весь проект**: без списка любой прохожий мог бы её
    израсходовать, и перестали бы обновляться чужие таблицы.

    Доступ — это **объединение** списков: админ проходит, даже если его нет
    среди обычных пользователей. Требовать присутствия в обоих значило бы
    завести состояние «админ без доступа», в котором роль есть, а выполнить ею
    нечего, и получалось бы оно молча — одной забытой правкой env.

    Пустые списки означают «никому»: бот, случайно поднятый без настройки, не
    должен оказаться открытым.
    """

    def __init__(
        self,
        allowed_telegram_ids: Iterable[int],
        admin_telegram_ids: Iterable[int] = (),
    ) -> None:
        self._admins = frozenset(admin_telegram_ids)
        self._allowed = frozenset(allowed_telegram_ids) | self._admins

    def is_allowed(self, telegram_id: int | None) -> bool:
        """Разрешено ли этому пользователю обращаться к боту."""
        if telegram_id is None:
            return False
        return telegram_id in self._allowed

    def is_admin(self, telegram_id: int | None) -> bool:
        """Админ ли это.

        Отдельный вопрос, а не поле роли у пользователя: ролей две, и вторая —
        это «все остальные». Заводить перечисление под булево значение значило
        бы обещать иерархию прав, которой нет.
        """
        if telegram_id is None:
            return False
        return telegram_id in self._admins
