"""Разбор дня, которым датировать операции чека.

Формат — голое число, день месяца:

    3

Этого достаточно, потому что период — полуинтервал длиной ровно месяц: число
месяца встречается в нём не более одного раза даже тогда, когда период
начинается не первого. В окне «25 июля — 25 августа» «25» — это июльское, «3» —
августовское, и спрашивать месяц незачем.

Отдельный парсер, а не форма :class:`~telegram_bot.parsers.CheckParser`:
у того каждая строка — правка позиции, он требует либо «!», либо разделитель, и
голое «3» уже сейчас падает в нём с текстом целиком про номера позиций. Стадия
дня правок не принимает вовсе, и общий парсер приглашал бы к обратному.
"""

from __future__ import annotations

from datetime import date, timedelta

from telegram_bot.i18n import LocaleFormat, t
from telegram_bot.parsers.results import ParseError

#: Больше двух цифр днём месяца быть не может. Проверяется до `int()`, чтобы
#: «20260803» получило внятный отказ, а не молчаливое «такого дня в периоде
#: нет»: пользователь прислал дату, а не день, и сказать надо именно это.
_MAX_DIGITS = 2


class DayParser:
    """Число из сообщения → день внутри границ периода."""

    @staticmethod
    def parse(raw: str | None, *, start_date: date, end_date: date) -> date:
        """День периода по его числу; `end_date` исключительна.

        Ответ ищется обходом самого окна, а не арифметикой по месяцам: обход
        и есть определение периода, он не может ошибиться на границе и не
        заводит вторую версию календаря рядом с той, что живёт в базе. Шагов
        не больше тридцати одного.
        """
        text = (raw or "").strip()
        if not text:
            raise ParseError(t("parse.day.usage"))

        if len(text) > _MAX_DIGITS or not text.isdecimal():
            raise ParseError(t("parse.day.not_a_number", value=text))

        number = int(text)
        for shift in range((end_date - start_date).days):
            day = start_date + timedelta(days=shift)
            if day.day == number:
                return day

        raise ParseError(
            t(
                "parse.day.out_of_period",
                start=LocaleFormat.day(start_date),
                end=LocaleFormat.day(end_date - timedelta(days=1)),
            )
        )
