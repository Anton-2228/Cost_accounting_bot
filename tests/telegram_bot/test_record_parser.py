"""Тесты разбора строки добавления операции."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from telegram_bot.api_client.models import Category, Currency, Period, PeriodStatus
from telegram_bot.parsers import ParseError, RecordParser

#: Период, начинающийся не первого числа: в нём видно, что число месяца
#: разбирается обходом окна, а не приставляется к текущему месяцу.
_PERIOD = Period(
    id=1,
    start_date=date(2026, 7, 25),
    end_date=date(2026, 8, 25),
    status=PeriodStatus.OPEN,
)

#: «Сегодня» для `_PERIOD`: период уже закончился, и всё его окно в прошлом.
#: Так проверяется сам разбор, не спотыкаясь о запрет датировать вперёд; сам
#: запрет проверяется отдельно, в :class:`TestFutureDay`.
_TODAY = _PERIOD.end_date

#: Период с первого числа короткого месяца: в нём есть число, которого в окне
#: нет вовсе. В окне `_PERIOD` таких чисел не бывает — месяц, начатый 25 июля,
#: перебирает все числа от 1 до 31.
_SHORT_PERIOD = Period(
    id=2,
    start_date=date(2026, 9, 1),
    end_date=date(2026, 10, 1),
    status=PeriodStatus.OPEN,
)

#: «Сегодня» для `_SHORT_PERIOD` — по той же причине, что и `_TODAY`.
_SHORT_TODAY = _SHORT_PERIOD.end_date


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


class TestDay:
    """Необязательный день первым словом."""

    def test_day_dates_the_record_and_leaves_the_rest_alone(
        self, categories: list[Category]
    ) -> None:
        """Число снимается со строки, остальное разбирается как прежде."""
        parsed = RecordParser.parse(
            "3 евро 500 еда обед", categories=categories, period=_PERIOD, today=_TODAY
        )

        assert parsed.added_at == date(2026, 8, 3)
        assert parsed.currency is Currency.EUR
        assert parsed.amount == Decimal("500")
        assert parsed.category_id == 1
        assert parsed.notes == "обед"

    def test_day_is_resolved_inside_the_period(self, categories: list[Category]) -> None:
        """Число ищется в окне периода, а не в текущем месяце.

        «25» в окне «25 июля — 25 августа» — июльское: `end_date` исключительна.
        """
        parsed = RecordParser.parse(
            "25 евро 500 еда", categories=categories, period=_PERIOD, today=_TODAY
        )
        assert parsed.added_at == date(2026, 7, 25)

    def test_without_a_day_the_date_is_left_to_api(self, categories: list[Category]) -> None:
        """Без числа дня нет и в разборе: сегодняшний день поставит api."""
        parsed = RecordParser.parse("евро 500 еда", categories=categories)
        assert parsed.added_at is None

    def test_day_outside_the_period_is_refused(self, categories: list[Category]) -> None:
        """Дня нет в периоде — отказ с его границами, операция не пишется.

        Границы названы включительно: `end_date` исключительна, и печатать её
        как конец периода значило бы обещать день, которого в нём нет.
        """
        with pytest.raises(ParseError) as error:
            RecordParser.parse(
                "31 евро 500 еда",
                categories=categories,
                period=_SHORT_PERIOD,
                today=_SHORT_TODAY,
            )

        assert "01.09.2026" in error.value.message
        assert "30.09.2026" in error.value.message

    def test_zero_is_refused_by_the_period_too(self, categories: list[Category]) -> None:
        """«0» — такое же число месяца, которого в периоде нет."""
        with pytest.raises(ParseError):
            RecordParser.parse(
                "0 евро 500 еда", categories=categories, period=_PERIOD, today=_TODAY
            )

    def test_notes_start_after_the_day(self, categories: list[Category]) -> None:
        """Пометка берётся из остатка уже без дня, а не со сдвигом на слово."""
        parsed = RecordParser.parse(
            "3 евро 500 еда обед в столовой", categories=categories, period=_PERIOD, today=_TODAY
        )
        assert parsed.notes == "обед в столовой"

    @pytest.mark.parametrize("raw", ["3", "3 евро", "3 евро 500"])
    def test_day_alone_is_not_a_command(self, raw: str, categories: list[Category]) -> None:
        """Строка со днём, но без остального — та же подсказка про формат.

        Счёт слов идёт после того, как день снят: иначе «3 евро 500» ругалось бы
        на валюту «3», хотя не хватает как раз категории.
        """
        with pytest.raises(ParseError, match="/add"):
            RecordParser.parse(raw, categories=categories, period=_PERIOD, today=_TODAY)

    def test_three_digits_are_not_a_day(self, categories: list[Category]) -> None:
        """Длинное число днём не становится и уходит в разбор валюты.

        Поэтому период за такую строку не запрашивается вовсе, а пользователь
        получает привычный отказ про валюту.
        """
        assert RecordParser.starts_with_day("032 евро 500 еда") is False
        with pytest.raises(ParseError) as error:
            RecordParser.parse("032 евро 500 еда", categories=categories)

        assert "032" in error.value.message
        assert "валюту" in error.value.message


class TestStartsWithDay:
    """Предикат, по которому команда решает, ехать ли за границами периода."""

    @pytest.mark.parametrize("raw", ["3 евро 500 еда", " 25 евро 500 еда", "3"])
    def test_leading_number_needs_the_period(self, raw: str) -> None:
        assert RecordParser.starts_with_day(raw) is True

    @pytest.mark.parametrize("raw", [None, "", "   ", "евро 500 еда", "500 еда обед"])
    def test_everything_else_does_not(self, raw: str | None) -> None:
        """В том числе пустая строка: за периодом ради отказа ходить незачем."""
        assert RecordParser.starts_with_day(raw) is False


class TestFutureDay:
    """Ненаступивший день в `/add`.

    Датировать вперёд нельзя: лист статистики сводит суммы к одной валюте по
    курсу на день операции, а курса на будущий день нет ни у одного источника, и
    перерисовка листа падала бы до самого этого дня.
    """

    def test_tomorrow_is_refused(self, categories: list[Category]) -> None:
        """Завтрашнее число периода отвергается, хотя лежит внутри окна."""
        with pytest.raises(ParseError) as error:
            RecordParser.parse(
                "4 евро 500 еда",
                categories=categories,
                period=_PERIOD,
                today=date(2026, 8, 3),
            )

        assert "03.08.2026" in error.value.message

    def test_today_is_allowed(self, categories: list[Category]) -> None:
        """Сегодня — последний допустимый день, а не первый запрещённый."""
        parsed = RecordParser.parse(
            "3 евро 500 еда",
            categories=categories,
            period=_PERIOD,
            today=date(2026, 8, 3),
        )
        assert parsed.added_at == date(2026, 8, 3)
