"""Тесты разбора правок «1,3 - молочка», цен «1,3-1999» и удалений «!1,3»."""

from __future__ import annotations

from decimal import Decimal

import pytest

from telegram_bot.parsers import CheckParser, ParseError


def test_several_numbers_share_one_value() -> None:
    """«1,3 - молочка» правит обе позиции сразу."""
    edits = CheckParser.parse("1,3 - молочка", count=3)
    assert len(edits) == 1
    assert edits[0].numbers == (1, 3)
    assert edits[0].value == "молочка"


def test_several_lines_are_separate_edits() -> None:
    """Правок в одном сообщении может быть несколько, по строке на каждую."""
    edits = CheckParser.parse("1 - молочка\n2 - бытовая химия", count=2)
    assert [(edit.numbers, edit.value) for edit in edits] == [
        ((1,), "молочка"),
        ((2,), "бытовая химия"),
    ]


def test_space_separated_numbers_are_accepted() -> None:
    """Номера можно разделить и пробелом: телефон подсказывает его чаще."""
    assert CheckParser.parse("1 2-молочка", count=2)[0].numbers == (1, 2)


def test_number_out_of_range_is_named() -> None:
    """Несуществующий номер отвергается с указанием, сколько позиций есть.

    Молча пропустить такую правку значило бы повторить старое поведение, при
    котором правки пользователя терялись без единого слова.
    """
    with pytest.raises(ParseError) as failure:
        CheckParser.parse("5 - молочка", count=3)
    assert "5" in failure.value.message


def test_garbage_is_refused() -> None:
    """Ввод без разделителя или без значения — подсказка о формате."""
    for text in ("молочка", "1 - ", "- молочка", "", None):
        with pytest.raises(ParseError):
            CheckParser.parse(text, count=3)


def test_repeated_number_is_refused() -> None:
    """Одна позиция дважды — отказ, а не молчаливое «побеждает последний».

    Молчаливый выбор последнего совпадения — ровно та ошибка, из-за которой
    подбор по псевдониму в старой версии писал операции не в ту категорию.
    """
    with pytest.raises(ParseError):
        CheckParser.parse("1 - молочка\n1,2 - химия", count=3)


def test_value_length_is_checked_before_api() -> None:
    """Слишком длинное значение объясняется по-русски, а не 422 без текста."""
    with pytest.raises(ParseError):
        CheckParser.parse("1 - " + "я" * 100, count=1, max_value_length=64)


def test_delete_line_has_no_value() -> None:
    """«!1» — удаление позиции, а не правка: значения у неё нет."""
    edits = CheckParser.parse("!1", count=3)
    assert len(edits) == 1
    assert edits[0].numbers == (1,)
    assert edits[0].delete
    assert edits[0].value == ""


def test_delete_takes_several_numbers() -> None:
    """«!1,2,13» убирает три позиции разом — теми же разделителями, что правка."""
    assert CheckParser.parse("!1,2,13", count=13)[0].numbers == (1, 2, 13)
    assert CheckParser.parse("!1 2", count=2)[0].numbers == (1, 2)


def test_delete_mixes_with_edits_in_one_message() -> None:
    """Удаление и правка живут в одном сообщении разными строками."""
    edits = CheckParser.parse("!1\n2 - молочка", count=2)
    assert [(edit.numbers, edit.delete, edit.value) for edit in edits] == [
        ((1,), True, ""),
        ((2,), False, "молочка"),
    ]


def test_delete_out_of_range_is_named() -> None:
    """Номер вне списка отвергается так же, как у обычной правки."""
    with pytest.raises(ParseError) as failure:
        CheckParser.parse("!5", count=3)
    assert "5" in failure.value.message


def test_delete_refuses_a_value() -> None:
    """«!1 - молочка» одинаково читается двумя способами — значит, отказ.

    И «!» без номеров тоже: удалять нечего, а угадывать «наверное, все» —
    худшее, что тут можно сделать.
    """
    for text in ("!1 - молочка", "!", "!х"):
        with pytest.raises(ParseError):
            CheckParser.parse(text, count=3)


def test_delete_and_edit_of_one_position_live_together() -> None:
    """«!1» и «1 - молочка» рядом — обе правки: они про разное.

    У удалённой позиции тип остаётся живым — она вернётся с ним же, — и
    назначить его заодно с удалением ничему не противоречит.
    """
    edits = CheckParser.parse("!1\n1 - молочка", count=3)
    assert [(edit.numbers, edit.delete, edit.value) for edit in edits] == [
        ((1,), True, ""),
        ((1,), False, "молочка"),
    ]


def test_two_values_for_one_position_are_refused() -> None:
    """Два типа одной позиции — отказ: применился бы молча последний."""
    with pytest.raises(ParseError):
        CheckParser.parse("1 - молочка\n1 - бытовая химия", count=3)


def test_numeric_tail_is_a_price() -> None:
    """«1,2,13-1999» ставит цену, а не тип с названием «1999»."""
    edits = CheckParser.parse("1,2,13-1999", count=13)
    assert len(edits) == 1
    assert edits[0].numbers == (1, 2, 13)
    assert edits[0].amount == Decimal("1999")
    assert edits[0].value == ""
    assert not edits[0].delete


def test_price_takes_a_dot_and_a_comma_alike() -> None:
    """Копейки набирают и точкой, и запятой: на телефоне под рукой запятая."""
    dot = CheckParser.parse("1-1999.50", count=1)[0]
    comma = CheckParser.parse("1-1999,50", count=1)[0]
    assert dot.amount == comma.amount == Decimal("1999.50")


def test_price_may_be_zero() -> None:
    """«1-0» — рабочий случай: позиция по акции досталась бесплатно."""
    assert CheckParser.parse("1-0", count=1)[0].amount == Decimal("0")


def test_price_finer_than_kopecks_is_refused() -> None:
    """Третий знак после запятой api отверг бы 422 без внятного текста."""
    with pytest.raises(ParseError):
        CheckParser.parse("1-1999,555", count=1)


def test_value_with_digits_inside_stays_a_value() -> None:
    """Ценой считается только хвост целиком из цифр — «3,2%» остаётся типом."""
    edits = CheckParser.parse("1 - молоко 3.2%", count=1)
    assert edits[0].amount is None
    assert edits[0].value == "молоко 3.2%"


def test_price_and_value_of_one_position_live_together() -> None:
    """«1 - молочка» и «1-500» рядом — правки о разном, обе применяются."""
    edits = CheckParser.parse("1 - молочка\n1-500", count=3)
    assert [(edit.value, edit.amount) for edit in edits] == [
        ("молочка", None),
        ("", Decimal("500")),
    ]


def test_two_prices_for_one_position_are_refused() -> None:
    """Две цены одной позиции — отказ: применилась бы молча последняя."""
    with pytest.raises(ParseError):
        CheckParser.parse("1-500\n1-700", count=3)
