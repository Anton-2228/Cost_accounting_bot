"""Тесты календарной арифметики учётного периода.

Каждый тест ниже соответствует конкретному дефекту старой реализации, которая
считала длину периода по статической таблице «дней в месяце» с февралём,
равным 28.
"""

from __future__ import annotations

from datetime import date

import pytest

from api.core.period import (
    catch_up_starts,
    contains,
    days_in_period,
    period_bounds,
    period_days,
    period_end,
    period_start_for,
    validate_reset_day,
)


def test_period_start_before_reset_day_belongs_to_previous_month() -> None:
    """Дата раньше дня сброса относится к периоду, начавшемуся в прошлом месяце."""
    assert period_start_for(date(2026, 7, 10), reset_day=15) == date(2026, 6, 15)


def test_period_start_on_reset_day_starts_new_period() -> None:
    """Сам день сброса открывает новый период, а не закрывает старый."""
    assert period_start_for(date(2026, 7, 15), reset_day=15) == date(2026, 7, 15)


def test_period_start_crosses_year_boundary() -> None:
    """Январская дата раньше дня сброса уходит в декабрь прошлого года."""
    assert period_start_for(date(2026, 1, 5), reset_day=15) == date(2025, 12, 15)


def test_reset_day_survives_leap_february() -> None:
    """День сброса не уезжает при переходе через февраль високосного года.

    Старая реализация прибавляла к дате фиксированные «дни месяца», где февраль
    всегда равнялся 28. Период, начавшийся 15 февраля 2024 года, заканчивался
    14 марта, и день сброса необратимо смещался: 15 → 14 → навсегда 14.
    """
    start = date(2024, 2, 15)
    assert period_end(start) == date(2024, 3, 15)
    assert days_in_period(start, period_end(start)) == 29


def test_reset_day_stable_across_full_year() -> None:
    """За двенадцать переходов подряд число дня сброса не меняется."""
    cursor = date(2024, 1, 28)
    for _ in range(12):
        cursor = period_end(cursor)
        assert cursor.day == 28


def test_bounds_are_half_open() -> None:
    """Границы полуинтервальные: `end_date` принадлежит уже следующему периоду.

    В старой версии записи отбирались включительным `BETWEEN`, поэтому операция
    в день `end_date` попадала сразу в два периода.
    """
    start, end = period_bounds(date(2026, 7, 20), reset_day=15)
    assert (start, end) == (date(2026, 7, 15), date(2026, 8, 15))
    assert contains(start, end, start) is True
    assert contains(start, end, end) is False


def test_period_days_cover_every_day_and_stop_before_end() -> None:
    """Дневных колонок ровно столько же, сколько суток в периоде.

    Прежде колонки строились как `range(days)` от начала, а записи отбирались
    включительным `BETWEEN`: операция в день `end_date` попадала в баланс и в
    лист операций, но ни в одну дневную колонку статистики.
    """
    start, end = period_bounds(date(2026, 7, 20), reset_day=15)
    days = period_days(start, end)

    assert len(days) == days_in_period(start, end)
    assert days[0] == start
    assert days[-1] == date(2026, 8, 14)
    assert end not in days


def test_catch_up_returns_nothing_while_period_is_running() -> None:
    """Пока период не закончился, догонять нечего."""
    assert catch_up_starts(date(2026, 7, 15), today=date(2026, 8, 1)) == []


def test_catch_up_recovers_every_missed_month() -> None:
    """Простой сервиса длиной в несколько месяцев не теряет ни одного периода.

    Старый ролловер срабатывал только при точном равенстве `today == end_date`,
    поэтому недоступность сервиса в день сброса означала безвозвратно
    пропущенный месяц.
    """
    missed = catch_up_starts(date(2026, 3, 15), today=date(2026, 7, 20))

    assert missed == [
        date(2026, 4, 15),
        date(2026, 5, 15),
        date(2026, 6, 15),
        date(2026, 7, 15),
    ]


def test_catch_up_includes_period_starting_today() -> None:
    """Период, начинающийся сегодня, должен быть создан сегодня же."""
    assert catch_up_starts(date(2026, 6, 15), today=date(2026, 7, 15)) == [date(2026, 7, 15)]


@pytest.mark.parametrize("reset_day", [0, 29, 31, -1])
def test_reset_day_outside_range_is_rejected(reset_day: int) -> None:
    """День сброса вне 1..28 отвергается.

    Ограничение несущее: именно оно гарантирует, что `replace(day=reset_day)` и
    сдвиг на месяц всегда дают существующую дату. 31 февраля не бывает.
    """
    with pytest.raises(ValueError, match="День сброса"):
        validate_reset_day(reset_day)


@pytest.mark.parametrize("reset_day", [1, 15, 28])
def test_reset_day_inside_range_is_accepted(reset_day: int) -> None:
    """Границы допустимого диапазона принимаются."""
    assert validate_reset_day(reset_day) == reset_day
