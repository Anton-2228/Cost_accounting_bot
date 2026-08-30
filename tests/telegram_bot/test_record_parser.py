"""Тесты разбора строки добавления операции."""

from __future__ import annotations

from decimal import Decimal

import pytest

from telegram_bot.api_client.models import Category, Currency, Source
from telegram_bot.parsers import ParseError, RecordParser


def test_full_line(categories: list[Category], sources: list[Source]) -> None:
    """Сумма, категория, счёт и пометка из остатка строки."""
    parsed = RecordParser.parse(
        "500 еда карта рубли обед в столовой",
        categories=categories,
        sources=sources,
    )

    assert parsed.amount == Decimal("500")
    assert parsed.category_id == 1
    assert parsed.category_title == "Продукты"
    assert parsed.category_is_income is False
    assert parsed.source_id == 1
    assert parsed.currency is Currency.RUB
    assert parsed.notes == "обед в столовой"


def test_notes_are_optional(categories: list[Category], sources: list[Source]) -> None:
    """Четыре слова — уже полная команда."""
    parsed = RecordParser.parse("500 еда карта евро", categories=categories, sources=sources)
    assert parsed.notes == ""
    assert parsed.currency is Currency.EUR


def test_income_category_is_marked(categories: list[Category], sources: list[Source]) -> None:
    """Вид категории приезжает в результат: по нему строится ответ пользователю.

    Сама сумма остаётся положительной — знак ставит api, и перевернуть операцию
    вводом нельзя.
    """
    parsed = RecordParser.parse("1000 зп карта рубли", categories=categories, sources=sources)
    assert parsed.category_is_income is True
    assert parsed.amount == Decimal("1000")


@pytest.mark.parametrize("raw", [None, "", "500", "500 еда", "500 еда карта"])
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
        RecordParser.parse("500 бензин карта рубли", categories=categories, sources=sources)

    assert "бензин" in error.value.message
    assert "Продукты" in error.value.message


def test_unknown_source_lists_available(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """То же для счёта."""
    with pytest.raises(ParseError) as error:
        RecordParser.parse("500 еда кошелёк рубли", categories=categories, sources=sources)

    assert "кошелёк" in error.value.message
    assert "Карта" in error.value.message


def test_amount_error_comes_first(categories: list[Category], sources: list[Source]) -> None:
    """Сумма разбирается раньше справочников: она и есть первая позиция."""
    with pytest.raises(ParseError, match="не похоже на сумму"):
        RecordParser.parse("абв еда карта рубли", categories=categories, sources=sources)


def test_long_notes_are_rejected(categories: list[Category], sources: list[Source]) -> None:
    """Слишком длинная пометка отсекается до запроса, а не ответом 422."""
    with pytest.raises(ParseError, match="Пометка длиннее"):
        RecordParser.parse(
            f"500 еда карта рубли {'а' * 600}",
            categories=categories,
            sources=sources,
        )


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("рубли", Currency.RUB),
        ("руб", Currency.RUB),
        ("₽", Currency.RUB),
        ("доллары", Currency.USD),
        ("баксов", Currency.USD),
        ("$", Currency.USD),
        ("евро", Currency.EUR),
        ("EUR", Currency.EUR),
        ("динары", Currency.RSD),
        ("динаров", Currency.RSD),
        ("rsd", Currency.RSD),
    ],
)
def test_currency_is_written_the_human_way(
    word: str,
    expected: Currency,
    categories: list[Category],
    sources: list[Source],
) -> None:
    """Валюта принимается в падежах, разговорных формах и знаками.

    Она указывается в каждой команде `/add` — это самое частое слово во всём
    вводе, — и требовать ISO-код ради покупки хлеба значило бы сделать бота
    неудобным ровно там, где им пользуются чаще всего.
    """
    parsed = RecordParser.parse(
        f"500 еда карта {word}",
        categories=categories,
        sources=sources,
    )
    assert parsed.currency is expected


def test_unknown_currency_lists_what_is_accepted(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """Непонятая валюта объясняется примером, а не молча уезжает в пометку."""
    with pytest.raises(ParseError) as error:
        RecordParser.parse("500 еда карта тугрики", categories=categories, sources=sources)

    assert "тугрики" in error.value.message
    assert "евро" in error.value.message


def test_notes_may_start_with_a_currency_word(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """Пометка вправе начинаться со слова, похожего на валюту.

    Ради этого валюта и сделана обязательной: будь она необязательной, границу
    «валюта или уже пометка» пришлось бы угадывать по содержимому слова, и
    «евроремонт» съедал бы сам себя.
    """
    parsed = RecordParser.parse(
        "500 еда карта рубли евро на сдачу",
        categories=categories,
        sources=sources,
    )

    assert parsed.currency is Currency.RUB
    assert parsed.notes == "евро на сдачу"
