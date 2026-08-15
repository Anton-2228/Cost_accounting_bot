"""Сообщения про Google-документ."""

from __future__ import annotations

from telegram_bot.api_client.models import Spreadsheet

#: Тот же шаблон, что в `api/core/messages.py`. Дублируется сознательно: там он
#: нужен уведомлению, которое собирается в фоне и едет готовым текстом, здесь —
#: ответу на команду. Общего места для него нет, потому что нет общего пакета.
_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{google_spreadsheet_id}"


class TableFormatter:
    """Ссылка на документ и его состояние."""

    @staticmethod
    def url(spreadsheet: Spreadsheet) -> str:
        """Адрес документа. Вызывать только когда `is_ready`."""
        return _URL_TEMPLATE.format(google_spreadsheet_id=spreadsheet.google_spreadsheet_id)

    @classmethod
    def link(cls, spreadsheet: Spreadsheet) -> str:
        """Сообщение со ссылкой либо с объяснением, почему её пока нет."""
        if not spreadsheet.is_ready:
            return (
                f"Таблица «{spreadsheet.title}» ещё создаётся — "
                "пришлю ссылку, как только будет готова"
            )
        return f"Таблица «{spreadsheet.title}»: {cls.url(spreadsheet)}"
