"""Разбор шагов мастера создания таблицы."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram_bot import constants
from telegram_bot.parsers.results import ParseError

# Локальная часть по RFC куда богаче, но здесь важно другое: не пропустить
# заведомо неверный адрес и не отвергнуть обычный. Старое правило
# `\w+@gmail.com` не экранировало точку (проходил `user@gmailXcom`) и отвергало
# адреса с точкой, дефисом и плюсом — то есть половину живых почт.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

#: Пользователь может обойтись без почты: доступ выдаётся отдельной командой.
SKIP_MARKERS = frozenset({"-", "нет", "пропустить"})


class OnboardingParser:
    """Разбор ответов на шаги `/start`: название, день сброса, пояс, почта."""

    @staticmethod
    def title(raw: str) -> str:
        """Название будущей таблицы."""
        title = raw.strip()
        if not title:
            raise ParseError("Название не может быть пустым")
        if len(title) > constants.SPREADSHEET_TITLE_MAX_LENGTH:
            raise ParseError(
                f"Название длиннее {constants.SPREADSHEET_TITLE_MAX_LENGTH} символов"
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
            raise ParseError(f"«{raw.strip()}» не похоже на число") from None

        if not constants.MIN_RESET_DAY <= day <= constants.MAX_RESET_DAY:
            raise ParseError(
                f"День должен быть от {constants.MIN_RESET_DAY} "
                f"до {constants.MAX_RESET_DAY}: этот день есть в каждом месяце"
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
            raise ParseError("Слишком длинное название пояса")
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ParseError(
                f"Пояса «{name}» не существует. Пример: Europe/Moscow"
            ) from None
        return name

    @staticmethod
    def email(raw: str) -> str | None:
        """Почта для доступа к таблице; `None`, если шаг пропущен."""
        value = raw.strip()
        if value.lower() in SKIP_MARKERS:
            return None
        if len(value) > constants.EMAIL_MAX_LENGTH:
            raise ParseError("Слишком длинный адрес")
        if not _EMAIL_RE.match(value):
            raise ParseError("Это не похоже на адрес почты")
        return value
