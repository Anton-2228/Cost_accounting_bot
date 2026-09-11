"""Текст уведомления по коду и параметрам от api."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from telegram_bot.formatting.table_formatter import TableFormatter
from telegram_bot.i18n import LocaleFormat, t
from telegram_bot.i18n.translator import required_params
from telegram_bot.logging import get_logger

logger = get_logger(__name__)

#: Код строк, пришедших из старой версии api: готовый русский текст лежит в
#: `params.text`. Недоставленных таких строк миграция не оставляет, но печатать
#: их бот всё равно умеет — это дешевле, чем объяснять пустоту.
LEGACY_CODE = "legacy"

#: Коды, которые бот умеет печатать, — у каждого есть шаблон
#: `notification.<код>`. Перечислены явно, а не выводятся из каталога: тест
#: сверяет этот список и с каталогом, и с кодами, которые шлёт api.
KNOWN_CODES = frozenset(
    {
        "table_ready",
        "import_ok",
        "rollover_done",
        "sync_failed",
        "sync_terminal",
        "access_failed",
        *(
            f"import_error.{name}"
            for name in (
                "empty",
                "unknown_id",
                "flag_invalid",
                "income_equals_cost",
                "name_empty",
                "name_not_one_word",
                "default_removed",
                "default_deactivated",
                "default_kind_changed",
                "duplicate_id",
                "duplicate_name",
                "duplicate_association",
                "duplicate_product_type",
            )
        ),
    }
)

#: Сколько символов ошибки Google показывать. Её текст приходит целиком и бывает
#: длинным, а сообщение Telegram ограничено 4096 символами.
_ERROR_PREVIEW_LENGTH = 1000


class NotificationFormatter:
    """Собирает фразу уведомления на языке обращения.

    **Никогда не бросает.** Уведомление печатается на пути `POST /notify`, и
    исключение там стало бы ответом 503, на который api повторяет запрос каждые
    несколько секунд — вечно, вместе со всеми следующими уведомлениями этого
    пользователя. Незнакомый код, недостающий параметр, испорченная дата — всё
    это превращается в общую фразу и запись в журнал.
    """

    @classmethod
    def render(cls, code: str, params: Mapping[str, Any]) -> str:
        """Текст уведомления либо общая фраза, если собрать его не вышло."""
        try:
            return cls._render(code, dict(params))
        except Exception:
            logger.exception("Не удалось собрать уведомление «%s» из %s", code, params)
            return t("notification.fallback")

    @classmethod
    def _render(cls, code: str, params: dict[str, Any]) -> str:
        """Собирает фразу, падая на любой несуразности во входных данных."""
        if code == LEGACY_CODE and isinstance(params.get("text"), str):
            return str(params["text"])
        if code not in KNOWN_CODES:
            logger.warning("Незнакомый код уведомления «%s»", code)
            return t("notification.fallback")

        key = f"notification.{code}"
        prepared = cls._prepare(code, params)
        missing = required_params(key) - prepared.keys()
        if missing:
            logger.warning("Уведомлению «%s» не хватает параметров %s", code, sorted(missing))
            return t("notification.fallback")
        return t(key, **prepared)

    @staticmethod
    def _prepare(code: str, params: dict[str, Any]) -> dict[str, Any]:
        """Доводит сырые параметры до вида, в котором их показывают.

        Api шлёт данные, а не их представление: дату — в ISO, документ — его
        идентификатором. Как это выглядит для человека, решается здесь, по
        языку обращения.
        """
        prepared = dict(params)
        if code == "table_ready":
            prepared["url"] = TableFormatter.url_for(str(params["google_spreadsheet_id"]))
        elif code == "rollover_done":
            prepared["start_date"] = LocaleFormat.day(date.fromisoformat(str(params["start_date"])))
        elif code == "sync_terminal":
            error = str(params.get("error", ""))
            if len(error) > _ERROR_PREVIEW_LENGTH:
                error = f"{error[:_ERROR_PREVIEW_LENGTH]}…"
            prepared["error"] = error
        return prepared
