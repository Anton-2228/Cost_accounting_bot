"""Разбор шагов мастера создания таблицы."""

from __future__ import annotations

import re
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram_bot import constants
from telegram_bot.i18n import t
from telegram_bot.parsers.results import ParseError

# Локальная часть по RFC куда богаче, но здесь важно другое: не пропустить
# заведомо неверный адрес и не отвергнуть обычный. Старое правило
# `\w+@gmail.com` не экранировало точку (проходил `user@gmailXcom`) и отвергало
# адреса с точкой, дефисом и плюсом — то есть половину живых почт.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")



def _normalize(raw: str) -> str:
    """Ответ в виде для сравнения со словами пропуска.

    NFC — одна и та же буква хинди или французского приходит с клавиатуры то
    составной, то готовой; `casefold` — регистр, который телефон ставит сам.
    """
    return unicodedata.normalize("NFC", raw.strip()).casefold()


#: «Пропустить» на всех языках бота: без почты и пояса можно обойтись — доступ
#: выдаётся потом отдельной кнопкой, а пояс берётся по умолчанию. Все языки
#: разом, а не язык пользователя: сменивший язык отвечает по привычке на
#: прежнем, и отказ из-за слова, которое он явно имел в виду, был бы отказом ни
#: за что. Хранятся уже нормализованными.
SKIP_MARKERS = frozenset(
    _normalize(word)
    for word in (
        "-",
        "нет", "пропустить",
        "no", "skip",
        "नहीं", "छोड़ें",
        "omitir", "saltar",
        "non", "passer", "ignorer",
    )
)


class OnboardingParser:
    """Разбор ответов на шаги `/start`: название, день сброса, пояс, почта."""

    @staticmethod
    def is_skip(raw: str) -> bool:
        """Отказ отвечать на шаг: «-» или «пропустить» на любом из языков."""
        return _normalize(raw) in SKIP_MARKERS

    @staticmethod
    def title(raw: str) -> str:
        """Название будущей таблицы."""
        title = raw.strip()
        if not title:
            raise ParseError(t("parse.onboarding.title_empty"))
        if len(title) > constants.SPREADSHEET_TITLE_MAX_LENGTH:
            raise ParseError(
                t("parse.onboarding.title_too_long", limit=constants.SPREADSHEET_TITLE_MAX_LENGTH)
            )
        return title

    @staticmethod
    def reset_day(raw: str) -> int:
        """День перехода на новый учётный месяц.

        Верхняя граница — 28-е, и это не осторожность: только при ней «то же
        число следующего месяца» всегда существует. 31 февраля не бывает.
        """
        try:
            day = int(raw.strip())
        except ValueError:
            raise ParseError(t("parse.onboarding.not_a_number", raw=raw.strip())) from None

        if not constants.MIN_RESET_DAY <= day <= constants.MAX_RESET_DAY:
            raise ParseError(
                t(
                    "parse.onboarding.reset_day_range",
                    min=constants.MIN_RESET_DAY,
                    max=constants.MAX_RESET_DAY,
                )
            )
        return day

    @staticmethod
    def timezone(raw: str) -> str:
        """Часовой пояс в формате IANA, например `Europe/Moscow`.

        Проверяется здесь, а не в api: в api неизвестный пояс всплыл бы только
        на ролловере — через месяц после ввода, ошибкой в логах фоновой задачи.
        """
        name = raw.strip()
        if len(name) > constants.TIMEZONE_MAX_LENGTH:
            raise ParseError(t("parse.onboarding.timezone_too_long"))
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ParseError(t("parse.onboarding.timezone_unknown", name=name)) from None
        return name

    @staticmethod
    def email(raw: str) -> str | None:
        """Почта для доступа к таблице; `None`, если шаг пропущен."""
        value = raw.strip()
        if OnboardingParser.is_skip(value):
            return None
        if len(value) > constants.EMAIL_MAX_LENGTH:
            raise ParseError(t("parse.onboarding.email_too_long"))
        if not _EMAIL_RE.match(value):
            raise ParseError(t("parse.onboarding.email_invalid"))
        return value
