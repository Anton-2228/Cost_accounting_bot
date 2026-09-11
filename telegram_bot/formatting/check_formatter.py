"""Сообщения разбора чека.

Раскладка списков повторяет старую версию, и это не ностальгия: она читается
лучше однострочной. Товар стоит отдельной строкой, а присвоенное ему значение —
с отступом под ним, поэтому взгляд идёт сверху вниз по названиям и цепляется
только за то, что нужно поправить.

Три несущих детали формата:

* **два блока через пустую строку.** Сверху то, что бот знает наверняка (тип из
  кэша, категория по закреплённому типу), снизу — то, что предложила модель и
  что стоит проверить;
* **новый тип печатается КАПСОМ.** Единственный способ увидеть, что тип ещё не
  существует ни у одной категории и будет заведён. В письме без регистра
  (хинди) капс ничего не меняет, и там вместо него пометка из каталога;
* **значение жирным.** Список из полусотни позиций иначе сливается в стену.

Жирный требует HTML, а названия товаров приезжают из чека — то есть из внешнего
источника. Поэтому всё подставляемое проходит через `html.escape`: товар
«M&M's» иначе развалил бы разметку всего сообщения, а `<b>` в названии позиции
съел бы половину списка.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from datetime import datetime
from html import escape

from telegram_bot.checks.draft import CheckDraft, DraftItem
from telegram_bot.formatting.money_formatter import MoneyFormatter
from telegram_bot.i18n import LocaleFormat, t

#: Заглушка на месте незаполненного типа или категории.
_EMPTY = "—"

#: Отступ под названием товара.
_INDENT = "    "


class CheckFormatter:
    """Шапка чека, нумерованные списки стадий и итог записи."""

    @staticmethod
    def header(draft: CheckDraft, *, left: int) -> str:
        """Шапка: магазин, время покупки, итог и сколько чеков осталось."""
        lines = [
            t("format.check.title_place", place=draft.retail_place)
            if draft.retail_place
            else t("format.check.title")
        ]
        if draft.purchased_at:
            lines.append(t("format.check.purchased", when=_moment(draft.purchased_at)))
        lines.append(
            t("format.check.total", amount=MoneyFormatter.format(draft.total, draft.currency))
        )
        lines.append(t("format.check.items", count=len(draft.items)))
        if left > 0:
            lines.append(t("format.check.queue_left", count=left))
        return "\n".join(lines)

    @classmethod
    def types(cls, draft: CheckDraft, known_types: Collection[str]) -> str:
        """Список «товар → тип»: сверху взятое из кэша, снизу подсказанное.

        Тип, которого нет ни у одной категории, выделяется — он будет заведён
        при записи чека, и увидеть это надо до, а не после.
        """
        return cls._two_blocks(
            draft,
            confirmed=lambda item: item.cached_type is not None,
            value=lambda item: item.product_type,
            shout=lambda item: bool(item.product_type) and item.product_type not in known_types,
        )

    @classmethod
    def categories(cls, draft: CheckDraft) -> str:
        """Список «товар → категория»: сверху определённое типом, снизу подсказанное."""
        return cls._two_blocks(
            draft,
            confirmed=lambda item: item.category_confirmed,
            value=lambda item: item.category_title,
            shout=lambda item: False,
        )

    @classmethod
    def _two_blocks(
        cls,
        draft: CheckDraft,
        *,
        confirmed: Callable[[DraftItem], bool],
        value: Callable[[DraftItem], str | None],
        shout: Callable[[DraftItem], bool],
    ) -> str:
        """Собирает список из двух блоков, разделённых пустой строкой.

        Пустой блок не оставляет за собой лишнего разрыва: у чека, где все
        товары знакомы, нижней части просто нет.
        """
        known: list[str] = []
        rest: list[str] = []
        for number, item in enumerate(draft.items, 1):
            entry = cls._entry(number, item, value(item), shout=shout(item))
            (known if confirmed(item) else rest).append(entry)
        return "\n\n".join(block for block in ("\n".join(known), "\n".join(rest)) if block)

    @staticmethod
    def _entry(number: int, item: DraftItem, value: str | None, *, shout: bool) -> str:
        """Две строки одной позиции: номер с названием и значение под ним.

        Номер стоит и у позиций из кэша, хотя в старой версии его там не было.
        Без номера их нельзя было поправить — и правка типа у уже знакомого
        товара молча терялась.
        """
        shown = value or _EMPTY
        if shout and value:
            shown = _emphasize_new(value)
        return f"{number}) {escape(item.name)}\n{_INDENT}<b>{escape(shown)}</b>"

    @staticmethod
    def saved(draft: CheckDraft, *, count: int) -> str:
        """Итог записи чека и то, чему бот на нём научился."""
        lines = [t("format.check.saved", count=count)]
        lines.extend(
            t("format.check.learned", name=name, product_type=product_type)
            for name, product_type in draft.learned()
        )
        return "\n".join(lines)

    @staticmethod
    def finished(*, saved: int, skipped: int) -> str:
        """Сообщение о конце очереди.

        Про пропущенные говорится отдельно и явно: они остались неразобранными,
        и без этой строки «чеки закончились» означало бы, что их больше нет.
        """
        lines = [t("format.check.finished"), t("format.check.finished_saved", count=saved)]
        if skipped:
            lines.append(t("format.check.finished_skipped", count=skipped))
        return "\n".join(lines)

    @staticmethod
    def hint(titles: Sequence[str]) -> str:
        """Строка «из чего выбирать» для правок категории."""
        return ", ".join(titles)


def _emphasize_new(value: str) -> str:
    """Новый тип: капсом, а в письме без регистра — с пометкой.

    Проверка не по языку, а по самому значению: тип мог прийти на другом
    языке, чем язык интерфейса, и выделить надо так, как его можно выделить.
    """
    upper = value.upper()
    return upper if upper != value else f"{value}{t('format.check.new_suffix')}"


def _moment(raw: str) -> str:
    """Время покупки из черновика на языке обращения.

    Черновик хранит время строкой ISO и форматируется при показе: язык может
    смениться посреди разбора, а черновик живёт в FSM дольше одного
    сообщения. Черновик, начатый до перехода на ISO, хранит уже готовую строку
    — её показываем как есть.
    """
    try:
        return LocaleFormat.moment(datetime.fromisoformat(raw))
    except ValueError:
        return raw
