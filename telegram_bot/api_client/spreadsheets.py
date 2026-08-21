"""Клиент раздела «учётные таблицы»."""

from __future__ import annotations

from telegram_bot import constants
from telegram_bot.api_client.http import ApiHttpClient
from telegram_bot.api_client.models import Spreadsheet


class SpreadsheetsClient:
    """Создание, чтение, удаление документа, доступы и просьба вчитать листы."""

    def __init__(self, http: ApiHttpClient) -> None:
        self._http = http

    async def create(
        self,
        *,
        telegram_id: int,
        title: str,
        reset_day: int,
        timezone: str,
        email: str | None,
    ) -> Spreadsheet:
        """Заводит таблицу пользователя.

        Возвращается сразу, без ожидания Google: документ создаст отдельный
        сервис по задаче из очереди и пришлёт ссылку уведомлением. Поэтому у
        свежей таблицы `google_spreadsheet_id` пуст, и это не ошибка.
        """
        body: dict[str, object] = {
            "telegram_id": telegram_id,
            "title": title,
            "reset_day": reset_day,
            "timezone": timezone,
        }
        if email is not None:
            body["email"] = email
        data = await self._http.post_data(
            "/spreadsheets",
            body=body,
            timeout=constants.CREATE_SPREADSHEET_TIMEOUT_SECONDS,
        )
        return Spreadsheet.model_validate(data)

    async def by_telegram_id(self, telegram_id: int) -> Spreadsheet:
        """Таблица пользователя; 404, если её ещё нет."""
        data = await self._http.get_data(f"/spreadsheets/by-telegram/{telegram_id}")
        return Spreadsheet.model_validate(data)

    async def list_by_telegram_id(self, telegram_id: int) -> list[Spreadsheet]:
        """Все таблицы пользователя за всё время, включая отвязанные.

        Другой маршрут, а не флаг у `by_telegram_id`: тот отвечает «с какой
        таблицей работать сейчас» и обязан оставаться единственным способом это
        узнать. Здесь же отвязанные — это цель запроса: траты на модель по ним
        остаются тратами пользователя. 404 по ресурсу `user` означает, что
        такого человека в базе нет вовсе.
        """
        items = await self._http.get_items(f"/users/{telegram_id}/spreadsheets")
        return [Spreadsheet.model_validate(item) for item in items]

    async def delete(self, spreadsheet_id: int) -> None:
        """Отвязывает таблицу от бота (сам Google-документ остаётся у владельца)."""
        await self._http.delete(f"/spreadsheets/{spreadsheet_id}")

    async def add_email(self, spreadsheet_id: int, email: str) -> None:
        """Просит открыть доступ к документу ещё одной почте.

        Доступ выдаёт `google_sheets_service`; отказ Google приедет отдельным
        уведомлением, а не ответом на этот вызов.
        """
        await self._http.post_data(
            f"/spreadsheets/{spreadsheet_id}/accesses",
            body={"email": email},
        )

    async def request_sync(self, spreadsheet_id: int) -> None:
        """Просит вчитать справочники из листов в базу.

        Ответ 202 означает «задача поставлена». Результат разбора — успех или
        русский текст ошибки с номером строки — приедет уведомлением: лист
        читает другой сервис, и в момент ответа результата ещё не существует.
        """
        await self._http.post_empty(
            f"/spreadsheets/{spreadsheet_id}/sync",
            timeout=constants.SYNC_TIMEOUT_SECONDS,
        )
