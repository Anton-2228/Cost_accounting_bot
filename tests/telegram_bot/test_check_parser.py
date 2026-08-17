"""Тесты разбора правок «1,3 - молочка»."""

from __future__ import annotations

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
