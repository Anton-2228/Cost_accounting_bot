"""Печать отчёта о тратах на модель по одному пользователю."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram_bot.api_client.models import LlmUsage, Period, Spreadsheet
from telegram_bot.i18n import LocaleFormat, t
from telegram_bot.logging import get_logger

logger = get_logger(__name__)

#: Знак валюты. Стоимость приезжает от провайдера в его валюте, а какая она —
#: в базе не записано: провайдер называет только число. Знак здесь соглашение
#: бота (и OpenAI, и OpenRouter выставляют счёт в долларах), а не факт из
#: данных, поэтому он один на весь отчёт и нигде не выбирается.
CURRENCY_SIGN = "$"

#: Точность показа денег. Разбор одного чека стоит доли цента, и двух знаков —
#: привычных для рублёвых сумм реестра — не хватило бы: месяц работы округлился
#: бы в ноль.
_COST_STEP = Decimal("0.0001")

#: Знаков после запятой в сумме — столько же, сколько у шага показа.
_COST_PLACES = 4


@dataclass(frozen=True)
class SpreadsheetUsage:
    """Одна таблица пользователя со своими периодами и замерами.

    Три части приезжают тремя запросами и собираются здесь, а не в api: период
    определяется датой в часовом поясе таблицы, и сложить одно с другим можно
    только зная всё сразу.
    """

    spreadsheet: Spreadsheet
    periods: Sequence[Period]
    usages: Sequence[LlmUsage]


@dataclass
class _Totals:
    """Накопленные итоги: деньги, токены, вызовы.

    `unknown_cost_calls` считается отдельно от денег, потому что пустой `cost`
    означает «провайдер не прислал цену», а не «вызов был бесплатным».
    Прибавить его нулём значило бы тихо занизить сумму ровно на неизвестное.
    """

    cost: Decimal = field(default_factory=lambda: Decimal(0))
    tokens: int = 0
    calls: int = 0
    unknown_cost_calls: int = 0

    def add(self, usage: LlmUsage) -> None:
        """Учитывает один замер."""
        self.calls += 1
        self.tokens += usage.total_tokens
        if usage.cost is None:
            self.unknown_cost_calls += 1
        else:
            self.cost += usage.cost

    def absorb(self, other: _Totals) -> None:
        """Прибавляет итоги другой части отчёта."""
        self.cost += other.cost
        self.tokens += other.tokens
        self.calls += other.calls
        self.unknown_cost_calls += other.unknown_cost_calls


class LlmUsageFormatter:
    """Собирает отчёт о тратах на модель.

    Сообщений несколько: шапка с итогом и по одному на таблицу. Одно на всё не
    годится — «таблицы × периоды» растёт с историей и упирается в лимит
    Telegram в 4096 символов, а резать текст по месту значило бы рвать таблицу
    посередине.
    """

    @classmethod
    def report(cls, telegram_id: int, items: Sequence[SpreadsheetUsage]) -> list[str]:
        """Отчёт целиком: первое сообщение — итог, дальше по таблице."""
        if not items:
            title = t("format.llm.title", telegram_id=telegram_id)
            return [f"{title}\n\n{t('format.llm.no_spreadsheets')}"]

        blocks: list[str] = []
        overall = _Totals()
        unlinked = 0

        for item in items:
            block, totals = cls._spreadsheet_block(item)
            blocks.append(block)
            overall.absorb(totals)
            if item.spreadsheet.is_unlinked:
                unlinked += 1

        return [cls._header(telegram_id, overall, len(items), unlinked), *blocks]

    # --- части отчёта ---

    @classmethod
    def _header(cls, telegram_id: int, totals: _Totals, tables: int, unlinked: int) -> str:
        """Шапка: сколько всего и по скольким таблицам."""
        lines = [
            t("format.llm.title", telegram_id=telegram_id),
            t("format.llm.total", totals=cls._totals(totals)),
            t("format.llm.tables_unlinked", count=tables, unlinked=unlinked)
            if unlinked
            else t("format.llm.tables", count=tables),
        ]
        if totals.unknown_cost_calls:
            lines.append(cls._unknown_note(totals.unknown_cost_calls))
        return "\n".join(lines)

    @classmethod
    def _spreadsheet_block(cls, item: SpreadsheetUsage) -> tuple[str, _Totals]:
        """Сообщение по одной таблице и её итоги."""
        title = (
            t("format.llm.spreadsheet_unlinked", title=item.spreadsheet.title)
            if item.spreadsheet.is_unlinked
            else t("format.llm.spreadsheet", title=item.spreadsheet.title)
        )

        by_period, outside, totals = cls._split_by_period(item)

        lines = [f"{title}: {cls._totals(totals)}"]
        if not totals.calls:
            return "\n".join([f"{title}", t("format.llm.no_usages")]), totals

        # Свежие периоды сверху: вопрос «сколько ушло за последний месяц»
        # задают чаще, чем «сколько было год назад», а листать сообщение до
        # конца ради него пришлось бы каждый раз.
        for period in sorted(item.periods, key=lambda one: one.start_date, reverse=True):
            period_totals = by_period.get(period.id)
            if period_totals is None:
                continue
            lines.append(f"  {cls._period_label(period)}: {cls._totals(period_totals)}")

        if outside.calls:
            lines.append(f"  {t('format.llm.outside_periods')}: {cls._totals(outside)}")

        if totals.unknown_cost_calls:
            lines.append(cls._unknown_note(totals.unknown_cost_calls))

        return "\n".join(lines), totals

    @classmethod
    def _split_by_period(
        cls,
        item: SpreadsheetUsage,
    ) -> tuple[dict[int, _Totals], _Totals, _Totals]:
        """Раскладывает замеры по периодам таблицы.

        Замеры, не попавшие ни в один период, идут в отдельную корзину, а не
        приписываются ближайшему: так бывает у чека, разобранного раньше первой
        операции, и приписать его чужому месяцу значило бы сделать цифру этого
        месяца неверной. Отдельной строкой сумма частей по-прежнему сходится с
        итогом.
        """
        timezone = cls._timezone(item.spreadsheet)
        by_period: dict[int, _Totals] = {}
        outside = _Totals()
        totals = _Totals()

        for usage in item.usages:
            totals.add(usage)
            period = cls._period_of(item.periods, cls._local_day(usage.created_at, timezone))
            target = outside if period is None else by_period.setdefault(period.id, _Totals())
            target.add(usage)

        return by_period, outside, totals

    # --- календарь ---

    @staticmethod
    def _timezone(spreadsheet: Spreadsheet) -> tzinfo:
        """Часовой пояс таблицы; при неизвестном имени — UTC.

        Пояс берётся у таблицы, а не у пользователя: именно в нём считаются
        границы суток во всём проекте, и у разных таблиц одного человека он
        может отличаться.

        Отказ вместо отчёта был бы худшим ответом: имя пояса приезжает из своей
        же базы, а несовпадение с базой tzdata в контейнере — свойство сборки, а
        не данных, и терять из-за него весь отчёт не за что.
        """
        try:
            return ZoneInfo(spreadsheet.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Неизвестный часовой пояс «%s» у таблицы %s, считаю в UTC",
                spreadsheet.timezone,
                spreadsheet.id,
            )
            return UTC

    @staticmethod
    def _local_day(moment: datetime, timezone: tzinfo) -> date:
        """Дата обращения в поясе таблицы.

        `created_at` — момент в UTC, а период ограничен датами. Без перевода
        вечерние вызовы уезжали бы в соседний день, а на границе месяца — в
        чужой период: ровно эта ошибка уже случалась в старой версии с датой
        операции.

        Метка без пояса считается UTC: так её и записала база, где колонка
        объявлена `timestamptz`.
        """
        aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
        return aware.astimezone(timezone).date()

    @staticmethod
    def _period_of(periods: Sequence[Period], day: date) -> Period | None:
        """Период, которому принадлежит день, или None."""
        return next((period for period in periods if period.contains(day)), None)

    @staticmethod
    def _period_label(period: Period) -> str:
        """Границы периода как «01.07.2026 — 31.07.2026».

        Последний день показывается включительно, а `end_date` исключительна:
        человеку «по 31.07» понятнее, чем «до 01.08», и именно так период
        выглядит в самой таблице.
        """
        last_day = period.end_date - timedelta(days=1)
        return f"{LocaleFormat.day(period.start_date)} — {LocaleFormat.day(last_day)}"

    # --- числа ---

    @classmethod
    def _totals(cls, totals: _Totals) -> str:
        """«0,8300 $ · 300 000 токенов · 28 вызовов»."""
        return " · ".join(
            (
                cls._cost(totals.cost),
                t("format.llm.tokens", count=LocaleFormat.integer(totals.tokens)),
                t("format.llm.calls", count=LocaleFormat.integer(totals.calls)),
            )
        )

    @classmethod
    def _cost(cls, cost: Decimal) -> str:
        """Сумма с точностью до одной десятитысячной.

        Ненулевая сумма, не дотянувшая до шага показа, печатается как «менее», а
        не как ноль: «0,0000 $» рядом с десятком вызовов выглядит как ошибка
        учёта, хотя учёт как раз верен.
        """
        quantized = cost.quantize(_COST_STEP)
        if quantized == 0 and cost > 0:
            return t("format.llm.less_than", amount=cls._money(_COST_STEP))
        return cls._money(quantized)

    @staticmethod
    def _money(value: Decimal) -> str:
        """Сумма в валюте провайдера с разделением разрядов."""
        return t(
            "format.money",
            amount=LocaleFormat.decimal(value, _COST_PLACES),
            sign=CURRENCY_SIGN,
        )

    @staticmethod
    def _unknown_note(calls: int) -> str:
        """Отметка о вызовах, цену которых провайдер не прислал."""
        return f"  {t('format.llm.unknown_cost', count=calls)}"
