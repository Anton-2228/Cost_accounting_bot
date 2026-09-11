"""Подстановка текста по ключу на языке обращения."""

from __future__ import annotations

from telegram_bot.i18n import language as _language
from telegram_bot.i18n.catalog import CATALOGS, placeholders
from telegram_bot.i18n.context import current_language
from telegram_bot.i18n.language import Language
from telegram_bot.logging import get_logger

logger = get_logger(__name__)


def t(key: str, /, **params: object) -> str:
    """Текст по ключу на языке текущего обращения."""
    return t_in(current_language(), key, **params)


def t_in(language: Language, key: str, /, **params: object) -> str:
    """Текст по ключу на явно указанном языке.

    Нужен там, где язык не совпадает с языком обращения: подпись над выбором
    языка на `/start` английская, кто бы его ни набрал.

    **Никогда не бросает.** Текст собирается в том числе на пути доставки
    уведомления и в границе ошибок `Manager`, и исключение отсюда превратилось
    бы в молчание вместо ответа. Поэтому отсутствующий ключ ищется в языке по
    умолчанию, а затем печатается сам ключ, а сломанная подстановка отдаёт
    шаблон как есть, — оба случая с записью в журнал.
    """
    template = _lookup(language, key)
    if template is None:
        logger.error("Нет текста «%s» ни на %s, ни на языке по умолчанию", key, language)
        return key
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.exception("Не удалось подставить параметры в текст «%s»", key)
        return template


def required_params(key: str) -> frozenset[str]:
    """Подстановки, которых ждёт шаблон на языке обращения.

    Нужен тем, кто собирает текст из чужих данных (уведомления от api): там
    недостающий параметр лучше заметить до подстановки и ответить общей
    фразой, чем показать человеку шаблон с фигурными скобками.
    """
    template = _lookup(current_language(), key)
    return frozenset() if template is None else placeholders(template)


def _lookup(language: Language, key: str) -> str | None:
    """Шаблон на языке, иначе на языке по умолчанию."""
    for candidate in (language, _language.DEFAULT_LANGUAGE):
        template = CATALOGS.get(candidate, {}).get(key)
        if template is not None:
            return template
    return None
