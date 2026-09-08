"""Тесты разбора строки добавления операции."""

from __future__ import annotations

from decimal import Decimal

import pytest

from telegram_bot.api_client.models import Category, Currency, Source
from telegram_bot.parsers import ParseError, RecordParser
from tests.telegram_bot.conftest import make_source


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
    assert parsed.currency is Currency.RUB
    assert parsed.notes == "обед в столовой"


def test_currency_defaults_to_source_currency(categories: list[Category]) -> None:
    """Без валюты операция записывается в валюте счёта, а не в валюте бота.

    Счета заведены здесь, а не в общей фикстуре: её читают и другие тесты, и
    менять всем валюту ради одного случая значило бы чинить не там.
    """
    sources = [
        make_source(source_id=1, title="Карта", currency=Currency.RUB, associations=["карта"]),
        make_source(source_id=2, title="Динарский", currency=Currency.RSD, associations=["дин"]),
    ]

    parsed = RecordParser.parse("500 еда дин", categories=categories, sources=sources)

    assert parsed.source_id == 2
    assert parsed.currency is Currency.RSD


def test_leading_currency_wins(categories: list[Category], sources: list[Source]) -> None:
    """Явная валюта в начале строки перекрывает валюту счёта."""
    parsed = RecordParser.parse("евро 500 еда карта обед", categories=categories, sources=sources)

    assert parsed.currency is Currency.EUR
    assert parsed.amount == Decimal("500")
    assert parsed.source_id == 1
    assert parsed.notes == "обед"


def test_notes_are_optional(categories: list[Category], sources: list[Source]) -> None:
    """Три слова — уже полная команда."""
    parsed = RecordParser.parse("500 еда карта", categories=categories, sources=sources)
    assert parsed.notes == ""
    assert parsed.currency is Currency.RUB


def test_income_category_is_marked(categories: list[Category], sources: list[Source]) -> None:
    """Вид категории приезжает в результат: по нему строится ответ пользователю.

    Сама сумма остаётся положительной — знак ставит api, и перевернуть операцию
    вводом нельзя.
    """
    parsed = RecordParser.parse("1000 зп карта", categories=categories, sources=sources)
    assert parsed.category_is_income is True
    assert parsed.amount == Decimal("1000")


@pytest.mark.parametrize(
    "raw",
    [None, "", "500", "500 еда", "евро", "евро 500", "евро 500 еда"],
)
def test_too_few_arguments(
    raw: str | None,
    categories: list[Category],
    sources: list[Source],
) -> None:
    """Неполная строка объясняется примером, а не «странным вводом».

    Указанная валюта не идёт в зачёт обязательным аргументам: иначе «евро 500
    еда» выглядело бы полной командой, а счёта в ней нет.
    """
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
    with pytest.raises(ParseError, match="не похоже"):
        RecordParser.parse("абв еда карта", categories=categories, sources=sources)


def test_unknown_first_word_mentions_both(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """На первом месте могли иметь в виду и сумму, и валюту — названы обе.

    «евра» — промах мимо валюты, а не мимо суммы, и ответ «не похоже на сумму»
    уводил бы от настоящей причины.
    """
    with pytest.raises(ParseError) as error:
        RecordParser.parse("евра 500 еда карта", categories=categories, sources=sources)

    assert "евра" in error.value.message
    assert "валюту" in error.value.message
    assert "евро" in error.value.message


def test_amount_error_stays_plain_after_currency(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """Если валюта уже указана, слово на месте суммы — заведомо сумма.

    Звать пользователя проверить валюту, которую он только что написал верно,
    значило бы сбивать с толку.
    """
    with pytest.raises(ParseError) as error:
        RecordParser.parse("евро абв еда карта", categories=categories, sources=sources)

    assert error.value.message == "«абв» не похоже на сумму"


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

    Пишут её редко — только когда она не совпадает с валютой счёта, — и отказ
    из-за написания пришёлся бы ровно на тот случай, когда пользователь помнит
    об особенности и сообщает о ней сам.
    """
    parsed = RecordParser.parse(
        f"{word} 500 еда карта",
        categories=categories,
        sources=sources,
    )
    assert parsed.currency is expected


def test_long_notes_are_rejected(categories: list[Category], sources: list[Source]) -> None:
    """Слишком длинная пометка отсекается до запроса, а не ответом 422."""
    with pytest.raises(ParseError, match="Пометка длиннее"):
        RecordParser.parse(
            f"500 еда карта {'а' * 600}",
            categories=categories,
            sources=sources,
        )


def test_notes_may_start_with_a_currency_word(
    categories: list[Category],
    sources: list[Source],
) -> None:
    """Пометка вправе начинаться со слова, похожего на валюту.

    Ради этого валюта и перенесена в начало строки: рядом с пометкой границу
    «валюта или уже пометка» пришлось бы угадывать по содержимому слова, и
    «евро на сдачу» укорачивало бы само себя. На первом месте валюта спорит
    только с числом, а с числом её не спутать.
    """
    parsed = RecordParser.parse(
        "500 еда карта евро на сдачу",
        categories=categories,
        sources=sources,
    )

    assert parsed.currency is Currency.RUB
    assert parsed.notes == "евро на сдачу"
