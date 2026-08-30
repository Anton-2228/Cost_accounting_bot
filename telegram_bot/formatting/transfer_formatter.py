"""Сообщения о переводах."""

from __future__ import annotations

from telegram_bot.api_client.models import Currency, Source, Transfer
from telegram_bot.formatting.money_formatter import MoneyFormatter
from telegram_bot.parsers.results import ParsedTransfer


class TransferFormatter:
    """Тексты про добавленный и удалённый перевод.

    Сумма перевода выражена в валюте счёта-источника — она единственная, которую
    называет пользователь, — поэтому валюта для подписи берётся оттуда же. Если
    счёт-получатель ведётся в другой валюте, зачисленное считается по курсу и
    видно в его остатке, а не в этом сообщении.
    """

    @staticmethod
    def saved(parsed: ParsedTransfer, transfer: Transfer, *, currency: Currency) -> str:
        """Подтверждение перевода."""
        lines = [
            f"Перевёл {MoneyFormatter.format(transfer.amount, currency)}",
            f"{parsed.from_source_title} → {parsed.to_source_title}",
        ]
        if parsed.notes:
            lines.append(f"Пометка: {parsed.notes}")
        lines.append(f"Дата: {transfer.added_at}")
        lines.append(f"id: {transfer.id}")
        return "\n".join(lines)

    @staticmethod
    def deleted(transfer: Transfer, *, sources: list[Source]) -> str:
        """Подтверждение удаления перевода."""
        titles = {source.id: source.title for source in sources}
        currencies = {source.id: source.currency for source in sources}
        sender = titles.get(transfer.from_source_id, "")
        receiver = titles.get(transfer.to_source_id, "")
        currency = currencies.get(transfer.from_source_id, Currency.RUB)
        lines = [
            f"Удалил перевод: {MoneyFormatter.format(transfer.amount, currency)}",
            f"{sender} → {receiver}" if sender and receiver else "",
            f"id: {transfer.id}",
        ]
        return "\n".join(line for line in lines if line)
