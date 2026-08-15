"""Сообщения об операциях."""

from __future__ import annotations

from telegram_bot.api_client.models import Category, Record, Source
from telegram_bot.formatting.money_formatter import MoneyFormatter
from telegram_bot.parsers.results import ParsedRecord


class RecordFormatter:
    """Тексты про добавленную и удалённую операцию."""

    @staticmethod
    def saved(parsed: ParsedRecord, record: Record) -> str:
        """Подтверждение записи.

        Идентификатор печатается всегда: по нему пользователь удаляет операцию
        через `/del id`, и другого способа его узнать у него нет.
        """
        kind = "доход" if parsed.category_is_income else "расход"
        lines = [
            f"Записал {kind}: {MoneyFormatter.format(record.amount)}",
            f"Категория: {parsed.category_title}",
            f"Счёт: {parsed.source_title}",
        ]
        if parsed.notes:
            lines.append(f"Пометка: {parsed.notes}")
        lines.append(f"Дата: {record.added_at}")
        lines.append(f"id: {record.id}")
        return "\n".join(lines)

    @staticmethod
    def deleted(
        record: Record,
        *,
        categories: list[Category],
        sources: list[Source],
    ) -> str:
        """Подтверждение удаления.

        Названия ищутся по спискам, а не запрашиваются поштучно: справочники и
        так уже загружены, а лишний круг по сети на каждое удаление ничего бы
        не добавил.
        """
        category = next((item.title for item in categories if item.id == record.category_id), "")
        source = next((item.title for item in sources if item.id == record.source_id), "")
        lines = [
            f"Удалил операцию: {MoneyFormatter.format(record.amount)}",
            f"Категория: {category}" if category else "",
            f"Счёт: {source}" if source else "",
            f"id: {record.id}",
        ]
        return "\n".join(line for line in lines if line)
