"""Тесты разбора строки добавления операции."""

from __future__ import annotations

from decimal import Decimal

import pytest

from telegram_bot.api_client.models import Category, Source
from telegram_bot.parsers import ParseError, RecordParser


def test_full_line(categories: list[Category], sources: list[Source]) -> None:
    """Сумма, категория, счёт и пометка из остатка строки."""
    parsed = RecordParser.parse(
        "500 еда карта обед в столовой",
        categories=categories,
        sources=sources,
    )

    assert parsed.amount == Decimal("500")
    assert parsed.category_id == 1
    assert parsed.category_title == "Продукты"
    assert parsed.category_is_income is False
    assert parsed.source_id == 1
    assert parsed.notes == "обед в столовой"


def test_notes_are_optional(categories: list[Category], sources: list[Source]) -> None:
    """Три слова — уже полная команда."""
    parsed = RecordParser.parse("500 еда карта", categories=categories, sources=sources)
    assert parsed.notes == ""


def test_income_category_is_marked(categories: list[Category], sources: list[Source]) -> None:
    """Вид категории приезжает в результат: по нему строится ответ пользователю.

    Сама сумма остаётся положительной — знак ставит api, и перевернуть операцию
    вводом нельзя.
    """
    parsed = RecordParser.parse("1000 зп карта", categories=categories, sources=sources)
    assert parsed.category_is_income is True
    assert parsed.amount == Decimal("1000")


@pytest.mark.parametrize("raw", [None, "", "500", "500 еда"])
def test_too_few_arguments(
    raw: str | None,
    categories: list[Category],
    sources: list[Source],
) -> None:
    """Неполная строка объясняется примером, а не «странным вводом»."""
    with pytest.raises(ParseError, match="/add"):
        RecordParser.parse(raw, categories=categories, sources=sources)


def test_unknown_category_lists_available(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """В ответ на опечатку показывается, из чего выбирать."""
    with pytest.raises(ParseError) as error:
        RecordParser.parse("500 бензин карта", categories=categories, sources=sources)

    assert "бензин" in error.value.message
    assert "Продукты" in error.value.message


def test_unknown_source_lists_available(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """То же для счёта."""
    with pytest.raises(ParseError) as error:
        RecordParser.parse("500 еда кошелёк", categories=categories, sources=sources)

    assert "кошелёк" in error.value.message
    assert "Карта" in error.value.message


def test_amount_error_comes_first(categories: list[Category], sources: list[Source]) -> None:
    """Сумма разбирается раньше справочников: она и есть первая позиция."""
    with pytest.raises(ParseError, match="не похоже на сумму"):
        RecordParser.parse("абв еда карта", categories=categories, sources=sources)


def test_long_notes_are_rejected(categories: list[Category], sources: list[Source]) -> None:
    """Слишком длинная пометка отсекается до запроса, а не ответом 422."""
    with pytest.raises(ParseError, match="Пометка длиннее"):
        RecordParser.parse(
            f"500 еда карта {'а' * 600}",
            categories=categories,
            sources=sources,
        )
