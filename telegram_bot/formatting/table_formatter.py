"""Сообщения про Google-документ."""

from __future__ import annotations

from telegram_bot.api_client.models import Spreadsheet
from telegram_bot.i18n import t

#: Адрес документа по его идентификатору. Единственная копия шаблона: api
#: присылает в уведомлении «таблица готова» идентификатор, а ссылку из него
#: собирает бот — тем же шаблоном, каким отвечает на кнопку «Получить таблицу».
_URL_TEMPLATE = "https://docs.google.com/spreadsheets/d/{google_spreadsheet_id}"


class TableFormatter:
    """Ссылка на документ и его состояние."""

    @staticmethod
    def url_for(google_spreadsheet_id: str) -> str:
        """Адрес документа по его идентификатору."""
        return _URL_TEMPLATE.format(google_spreadsheet_id=google_spreadsheet_id)

    @classmethod
    def url(cls, spreadsheet: Spreadsheet) -> str:
        """Адрес документа. Вызывать только когда `is_ready`."""
        return cls.url_for(spreadsheet.google_spreadsheet_id or "")

    @classmethod
    def link(cls, spreadsheet: Spreadsheet) -> str:
        """Сообщение со ссылкой либо с объяснением, почему её пока нет."""
        if not spreadsheet.is_ready:
            return t("format.table.creating", title=spreadsheet.title)
        return t("format.table.link", title=spreadsheet.title, url=cls.url(spreadsheet))
