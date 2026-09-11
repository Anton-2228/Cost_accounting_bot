"""Сообщения об операциях."""

from __future__ import annotations

from telegram_bot.api_client.models import Category, Record
from telegram_bot.formatting.money_formatter import MoneyFormatter
from telegram_bot.i18n import LocaleFormat, t
from telegram_bot.parsers.results import ParsedRecord


class RecordFormatter:
    """Тексты про добавленную и удалённую операцию."""

    @staticmethod
    def saved(parsed: ParsedRecord, record: Record) -> str:
        """Подтверждение записи.

        Идентификатор печатается всегда: по нему пользователь удаляет операцию
        через `/del id`, и другого способа его узнать у него нет.
        """
        amount = MoneyFormatter.format(record.amount, record.currency)
        headline = (
            t("format.record.saved_income", amount=amount)
            if parsed.category_is_income
            else t("format.record.saved_expense", amount=amount)
        )
        lines = [headline, t("format.record.category", title=parsed.category_title)]
        if parsed.notes:
            lines.append(t("format.record.notes", notes=parsed.notes))
        lines.append(t("format.record.date", date=LocaleFormat.day(record.added_at)))
        lines.append(t("format.record.id", id=record.id))
        return "\n".join(lines)

    @staticmethod
    def deleted(record: Record, *, categories: list[Category]) -> str:
        """Подтверждение удаления.

        Название ищется по списку, а не запрашивается поштучно: справочник и
        так уже загружен, а лишний круг по сети на каждое удаление ничего бы не
        добавил.
        """
        category = next((item.title for item in categories if item.id == record.category_id), "")
        lines = [
            t(
                "format.record.deleted",
                amount=MoneyFormatter.format(record.amount, record.currency),
            ),
            t("format.record.category", title=category) if category else "",
            t("format.record.id", id=record.id),
        ]
        return "\n".join(line for line in lines if line)
