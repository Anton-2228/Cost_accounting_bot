"""Тесты разбора дня, которым датируется чек."""

from __future__ import annotations

from datetime import date

import pytest

from telegram_bot.parsers import DayParser, ParseError

#: Период, начинающийся не первого числа: именно он делает разбор
#: содержательным. «25» в нём — июльское, «3» — августовское.
_START = date(2026, 7, 25)
_END = date(2026, 8, 25)


def _parse(raw: str | None, start: date = _START, end: date = _END) -> date:
    return DayParser.parse(raw, start_date=start, end_date=end)


def test_number_resolves_inside_the_period() -> None:
    """Число месяца находит свой день, в какой бы из двух месяцев он ни попал."""
    assert _parse("25") == date(2026, 7, 25)
    assert _parse("31") == date(2026, 7, 31)
    assert _parse("1") == date(2026, 8, 1)
    assert _parse("3") == date(2026, 8, 3)


def test_both_edges_are_reachable() -> None:
    """Обе границы окна доступны: начало включено, конец — за день до `end_date`.

    Ровно здесь ошибается разбор, считающий по месяцам вместо обхода окна.
    """
    assert _parse("25") == _START
    assert _parse("24") == date(2026, 8, 24)


def test_exclusive_end_never_wins_its_own_number() -> None:
    """Число, общее у начала и у `end_date`, достаётся началу.

    25 августа — уже следующий период, и отдать «25» ему значило бы записать
    чек в чужой месяц, попав притом в правильное число.
    """
    assert _parse("25") == _START
    assert _parse("25") != _END


@pytest.mark.parametrize("raw", ["0", "32", "-1", "", "   ", None])
def test_impossible_input_is_refused(raw: str | None) -> None:
    """Пустое и невозможное число разбору не поддаются."""
    with pytest.raises(ParseError):
        _parse(raw)


def test_category_edit_is_not_a_day() -> None:
    """Правка категорий на стадии дня — просто не число, а не тихая правка.

    Стадия задаёт один вопрос: принять здесь правку значило бы позволить типу
    или категории уехать после того, как чек показан готовым.
    """
    with pytest.raises(ParseError):
        _parse("1,3 - молочка")


def test_date_instead_of_a_day_is_refused() -> None:
    """Дата целиком — не день месяца, и отказ говорит именно это."""
    for raw in ("3 марта", "03.08.2026", "20260803"):
        with pytest.raises(ParseError):
            _parse(raw)


def test_out_of_period_names_the_bounds() -> None:
    """Отказ по дню вне периода называет границы — иначе он необъясним.

    Конец называется включительно, на день раньше `end_date`: иначе отказ
    рекламировал бы день, который сам же и отвергает.
    """
    with pytest.raises(ParseError) as error:
        _parse("24", start=date(2026, 7, 25), end=date(2026, 7, 27))
    assert "26" in error.value.message


def test_month_long_period_from_the_first() -> None:
    """Период с первого числа: календарный месяц целиком."""
    start, end = date(2026, 3, 1), date(2026, 4, 1)
    assert _parse("1", start, end) == start
    assert _parse("31", start, end) == date(2026, 3, 31)
    with pytest.raises(ParseError):
        _parse("32", start, end)


def test_period_anchored_at_the_latest_reset_day() -> None:
    """`reset_day=28` — предельный якорь, и февраль его не ломает."""
    start, end = date(2027, 1, 28), date(2027, 2, 28)
    assert _parse("28", start, end) == start
    assert _parse("27", start, end) == date(2027, 2, 27)
    # 28 февраля — уже следующий период, и число «28» досталось январю.
    assert _parse("28", start, end) != date(2027, 2, 28)


def test_leap_february_is_not_recomputed() -> None:
    """Високосный февраль разбирается сам собой: окно обходится, а не считается."""
    start, end = date(2028, 2, 15), date(2028, 3, 15)
    assert _parse("29", start, end) == date(2028, 2, 29)
    assert _parse("14", start, end) == date(2028, 3, 14)
    assert _parse("15", start, end) == start
