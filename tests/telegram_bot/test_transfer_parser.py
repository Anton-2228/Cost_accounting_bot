"""Тесты разбора строки перевода."""

from __future__ import annotations

from decimal import Decimal

import pytest

from telegram_bot.api_client.models import Source
from telegram_bot.parsers import ParseError, TransferParser


def test_full_line(sources: list[Source]) -> None:
    """Сумма, счёт-отправитель, счёт-получатель и пометка."""
    parsed = TransferParser.parse("1000 нал карта отложил", sources=sources)

    assert parsed.amount == Decimal("1000")
    assert parsed.from_source_id == 2
    assert parsed.from_source_title == "Наличные"
    assert parsed.to_source_id == 1
    assert parsed.to_source_title == "Карта"
    assert parsed.notes == "отложил"


def test_notes_are_passed_through(sources: list[Source]) -> None:
    """Пометка попадает в результат.

    Старая версия её не отправляла вовсе, и смысл перевода терялся: в реестре
    оставалось движение денег без единого пояснения.
    """
    parsed = TransferParser.parse("100 карта нал на продукты", sources=sources)
    assert parsed.notes == "на продукты"


def test_same_source_is_rejected(sources: list[Source]) -> None:
    """Перевод сам в себя объясняется до обращения к api."""
    with pytest.raises(ParseError, match="совпадают"):
        TransferParser.parse("100 карта карта", sources=sources)


def test_fractional_amount(sources: list[Source]) -> None:
    """Дробная сумма проходит.

    Отдельный тест потому, что ровно на этом старая версия падала: валидация
    принимала `float`, а команда затем делала `int(args[0])` и получала
    `ValueError`, который никто не ловил.
    """
    parsed = TransferParser.parse("12,5 карта нал", sources=sources)
    assert parsed.amount == Decimal("12.5")


def test_unknown_sender(sources: list[Source]) -> None:
    """Неизвестный отправитель назван прямо, а не «источник»."""
    with pytest.raises(ParseError) as error:
        TransferParser.parse("100 копилка карта", sources=sources)
    assert "отправителя" in error.value.message


def test_unknown_receiver(sources: list[Source]) -> None:
    """То же для получателя."""
    with pytest.raises(ParseError) as error:
        TransferParser.parse("100 карта копилка", sources=sources)
    assert "получателя" in error.value.message


@pytest.mark.parametrize("raw", [None, "", "100", "100 карта"])
def test_too_few_arguments(raw: str | None, sources: list[Source]) -> None:
    """Неполная строка объясняется примером."""
    with pytest.raises(ParseError, match="/add_trans"):
        TransferParser.parse(raw, sources=sources)
