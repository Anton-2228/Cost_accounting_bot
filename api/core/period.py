"""Календарная арифметика учётного периода.

Учётный «месяц» идёт от выбранного пользователем дня сброса (`reset_day`) до
того же числа следующего календарного месяца. Границы **полуинтервальные**:
``[start_date, end_date)`` — день `end_date` принадлежит уже следующему периоду.

Старая реализация (`api/core/period.py` в предыдущей версии) считала длину
периода по статической таблице «дней в месяце», где февраль всегда равнялся 28.
В високосный год день сброса необратимо уезжал на сутки назад и никогда не
возвращался: 15 → 14 → навсегда 14. Здесь вся арифметика календарная
(:mod:`dateutil.relativedelta`), а `reset_day` ограничен 28-м числом — только
так сдвиг на месяц всегда даёт существующую дату.

Модуль состоит из чистых функций: «сегодня» приходит параметром или берётся из
часового пояса конкретной таблицы, но никогда — из локального времени процесса.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from api.core import constants


def now_in_timezone(timezone: str) -> datetime:
    """Текущий момент в часовом поясе таблицы (timezone-aware)."""
    return datetime.now(ZoneInfo(timezone))


def today_in_timezone(timezone: str) -> date:
    """Сегодняшняя дата в часовом поясе таблицы.

    Именно она, а не `date.today()` процесса, определяет день операции. Для
    `Europe/Moscow` сутки сменяются в 21:00 UTC, поэтому вечерняя операция при
    расчёте в UTC уехала бы во вчерашний день, а на границе месяца — в чужой
    период.
    """
    return now_in_timezone(timezone).date()


def validate_reset_day(reset_day: int) -> int:
    """Проверяет, что день сброса попадает в допустимый диапазон 1..28."""
    if not constants.MIN_RESET_DAY <= reset_day <= constants.MAX_RESET_DAY:
        raise ValueError(
            f"День сброса должен быть от {constants.MIN_RESET_DAY} "
            f"до {constants.MAX_RESET_DAY}, получено {reset_day}"
        )
    return reset_day


def period_start_for(day: date, reset_day: int) -> date:
    """Начало учётного периода, которому принадлежит указанная дата."""
    validate_reset_day(reset_day)
    anchor = day.replace(day=reset_day)
    if day >= anchor:
        return anchor
    return anchor - relativedelta(months=1)


def period_end(start_date: date) -> date:
    """Конец периода — то же число следующего месяца, **не включая** этот день."""
    return start_date + relativedelta(months=1)


def period_bounds(day: date, reset_day: int) -> tuple[date, date]:
    """Полуинтервальные границы ``[start, end)`` периода, содержащего дату."""
    start_date = period_start_for(day, reset_day)
    return start_date, period_end(start_date)


def contains(start_date: date, end_date: date, day: date) -> bool:
    """Принадлежит ли дата полуинтервалу ``[start_date, end_date)``."""
    return start_date <= day < end_date


def days_in_period(start_date: date, end_date: date) -> int:
    """Число суток в периоде (столько дневных колонок на листе статистики)."""
    return (end_date - start_date).days


def period_days(start_date: date, end_date: date) -> list[date]:
    """Все даты периода по возрастанию.

    Ровно `days_in_period` элементов, последний — `end_date - 1 день`. В старой
    версии колонки статистики строились как ``range(days)`` от начала, а записи
    отбирались включительным `BETWEEN`, из-за чего операция в день `end_date`
    попадала в баланс и в лист операций, но ни в одну дневную колонку.
    """
    total = days_in_period(start_date, end_date)
    return [start_date + relativedelta(days=offset) for offset in range(total)]


def catch_up_starts(last_start: date, today: date) -> list[date]:
    """Начала периодов, которые нужно создать после `last_start` включительно до `today`.

    Возвращает пустой список, если период `last_start` ещё не закончился. Если
    сервис не работал несколько месяцев — вернёт все пропущенные начала подряд,
    поэтому ролловер догоняет любое отставание.

    Старая версия сравнивала ``today != end_date`` точным равенством: простой в
    день сброса означал безвозвратно пропущенный месяц.
    """
    starts: list[date] = []
    cursor = last_start
    while True:
        cursor = period_end(cursor)
        if cursor > today:
            return starts
        starts.append(cursor)
