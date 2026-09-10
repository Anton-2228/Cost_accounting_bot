"""Тесты разбора строки добавления операции."""

from __future__ import annotations

from decimal import Decimal

import pytest

from telegram_bot.api_client.models import Category, Currency
from telegram_bot.parsers import ParseError, RecordParser


def test_full_line(categories: list[Category]) -> None:
    """Валюта, сумма, категория и пометка из остатка строки."""
    parsed = RecordParser.parse("евро 500 еда обед в столовой", categories=categories)

    assert parsed.currency is Currency.EUR
    assert parsed.amount == Decimal("500")
    assert parsed.category_id == 1
    assert parsed.category_title == "Продукты"
    assert parsed.category_is_income is False
    assert parsed.notes == "обед в столовой"


def test_notes_are_optional(categories: list[Category]) -> None:
    """Три слова — уже полная команда."""
    parsed = RecordParser.parse("рубли 500 еда", categories=categories)
    assert parsed.notes == ""
    assert parsed.currency is Currency.RUB


def test_income_category_is_marked(categories: list[Category]) -> None:
    """Вид категории приезжает в результат: по нему строится ответ пользователю.

    Сама сумма остаётся положительной — знак ставит api, и перевернуть операцию
    вводом нельзя.
    """
    parsed = RecordParser.parse("рубли 1000 зп", categories=categories)
    assert parsed.category_is_income is True
    assert parsed.amount == Decimal("1000")


@pytest.mark.parametrize("raw", [None, "", "евро", "евро 500"])
def test_too_few_arguments(raw: str | None, categories: list[Category]) -> None:
    """Неполная строка объясняется примером, а не «странным вводом»."""
    with pytest.raises(ParseError, match="/add"):
        RecordParser.parse(raw, categories=categories)


def test_currency_is_required(categories: list[Category]) -> None:
    """Без валюты команда не разбирается вовсе.

    Подставить валюту больше неоткуда: счетов, у которых она была, в системе
    нет. Прежде строка «500 еда карта» была полной командой — теперь первое
    слово обязано быть валютой, и «500» ею не является.
    """
    with pytest.raises(ParseError) as error:
        RecordParser.parse("500 еда обед", categories=categories)

    assert "500" in error.value.message
    assert "валюту" in error.value.message
    assert "/add" in error.value.message


def test_unknown_currency_lists_examples(categories: list[Category]) -> None:
    """Промах по написанию валюты называет причину и показывает примеры."""
    with pytest.raises(ParseError) as error:
        RecordParser.parse("евра 500 еда", categories=categories)

    assert "евра" in error.value.message
    assert "евро" in error.value.message


def test_unknown_category_lists_available(categories: list[Category]) -> None:
    """В ответ на опечатку показывается, из чего выбирать."""
    with pytest.raises(ParseError) as error:
        RecordParser.parse("рубли 500 бензин", categories=categories)

    assert "бензин" in error.value.message
    assert "Продукты" in error.value.message


def test_amount_error_is_plain(categories: list[Category]) -> None:
    """Слово на месте суммы — заведомо сумма: валюту уже разобрали.

    Звать пользователя проверить валюту, которую он только что написал верно,
    значило бы сбивать с толку.
    """
    with pytest.raises(ParseError) as error:
        RecordParser.parse("евро абв еда", categories=categories)

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
) -> None:
    """Валюта принимается в падежах, разговорных формах и знаками.

    Пишут её теперь каждый раз, и отказ из-за написания пришёлся бы на самую
    частую команду бота.
    """
    parsed = RecordParser.parse(f"{word} 500 еда", categories=categories)
    assert parsed.currency is expected


def test_long_notes_are_rejected(categories: list[Category]) -> None:
    """Слишком длинная пометка отсекается до запроса, а не ответом 422."""
    with pytest.raises(ParseError, match="Пометка длиннее"):
        RecordParser.parse(f"рубли 500 еда {'а' * 600}", categories=categories)


def test_notes_may_start_with_a_currency_word(categories: list[Category]) -> None:
    """Пометка вправе начинаться со слова, похожего на валюту.

    Ради этого валюта и стоит в начале строки: рядом с пометкой границу
    «валюта или уже пометка» пришлось бы угадывать по содержимому слова, и
    «евро на сдачу» укорачивало бы само себя. На первом месте валюта ни с чем
    не спорит вовсе.
    """
    parsed = RecordParser.parse("рубли 500 еда евро на сдачу", categories=categories)

    assert parsed.currency is Currency.RUB
    assert parsed.notes == "евро на сдачу"
