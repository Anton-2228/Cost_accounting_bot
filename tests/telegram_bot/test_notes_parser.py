"""Тесты разбора пометки — текста, который ляжет в `notes` операции."""

from __future__ import annotations

import pytest

from telegram_bot import constants
from telegram_bot.parsers import NotesParser, ParseError


def test_text_becomes_the_note_as_is() -> None:
    """Формата у пометки нет: ею становится присланное целиком."""
    assert NotesParser.parse("магазин у дома") == "магазин у дома"


def test_edges_are_trimmed() -> None:
    """Пробелы по краям срезаются: в листе операций они остались бы навсегда."""
    assert NotesParser.parse("  обед с коллегами  ") == "обед с коллегами"


def test_inner_spaces_survive() -> None:
    """Внутри пометки текст не трогают: это не разбор, а текст пользователя."""
    assert NotesParser.parse("обед   с   коллегами") == "обед   с   коллегами"


def test_edits_are_not_parsed() -> None:
    """«1,3 - молочка» — пометка, а не правка позиций.

    Стадия пометки задаёт один вопрос и правок не принимает вовсе; принять их
    здесь значило бы позволить категории уехать после того, как чек показан
    готовым.
    """
    assert NotesParser.parse("1,3 - молочка") == "1,3 - молочка"


class TestEmpty:
    """Пустая пометка законна ровно там, где её не спрашивали."""

    def test_refused_by_default(self) -> None:
        """На стадии пометки пустое сообщение — промах, а не «убрать»."""
        with pytest.raises(ParseError):
            NotesParser.parse("")

    def test_whitespace_counts_as_empty(self) -> None:
        with pytest.raises(ParseError):
            NotesParser.parse("   ")

    def test_none_counts_as_empty(self) -> None:
        """Сообщение без текста — картинка или стикер — доезжает сюда как `None`."""
        with pytest.raises(ParseError):
            NotesParser.parse(None)

    def test_allowed_for_the_optional_tail(self) -> None:
        """У `/add` пустой хвост значит «операция без пометки»."""
        assert NotesParser.parse("", allow_empty=True) == ""
        assert NotesParser.parse(None, allow_empty=True) == ""


class TestRefusals:
    """Два правила, которым пометка обязана подчиняться."""

    def test_multiline_is_refused(self) -> None:
        """Блок стадии — одно сообщение, и пометка не должна его растягивать."""
        with pytest.raises(ParseError):
            NotesParser.parse("магазин\nу дома")

    def test_multiline_is_refused_before_length(self) -> None:
        """Короткая многострочная получает отказ про строки, а не про длину."""
        with pytest.raises(ParseError) as error:
            NotesParser.parse("а\nб")

        assert "512" not in error.value.message

    def test_limit_is_the_column_width(self) -> None:
        assert NotesParser.parse("я" * constants.NOTES_MAX_LENGTH)

    def test_one_over_the_limit_is_refused(self) -> None:
        """Длиннее колонки `records.notes` — отказ: api отверг бы это сам."""
        with pytest.raises(ParseError):
            NotesParser.parse("я" * (constants.NOTES_MAX_LENGTH + 1))

    def test_length_is_measured_after_trimming(self) -> None:
        """Пробелы по краям в предел не считаются: их всё равно срежут."""
        note = "я" * constants.NOTES_MAX_LENGTH
        assert NotesParser.parse(f"  {note}  ") == note
