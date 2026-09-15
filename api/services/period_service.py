"""Чтение учётных периодов и дневных итогов по категориям."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.domain.category_daily_total import CategoryDailyTotal
from api.domain.period import Period
from api.exceptions.base import NotFoundError
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services._periods import ensure_current_period, resolve_period, today_for
from api.services.base import BaseSpreadsheetService
from api.services.exchange_rate_service import ExchangeRateService


class PeriodService(BaseSpreadsheetService):
    """Периоды документа и статистика по ним.

    Чтение архива ничего не создаёт: прошлые периоды заводят ролловер и сама
    история, и появляться от просмотра они не должны. Исключение одно и
    намеренное — :meth:`current`, см. её докстринг.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        periods: PeriodRepository,
        records: RecordRepository,
        rates: ExchangeRateService,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._periods = periods
        self._records = records
        self._rates = rates

    async def list_all(self, spreadsheet_id: int) -> list[Period]:
        """Все периоды документа по возрастанию даты начала, в том числе отвязанного.

        Документ ищется с `include_deleted=True` и без проверки готовности — по
        той же причине, что и в чтении замеров модели: отвязывание мягкое, и
        `_get_ready` отдавал бы 404 ровно на том случае, ради которого чтение
        всей истории и нужно. Отчёт о тратах на модель раскладывает их по
        периодам **всех** таблиц пользователя, включая отвязанные, и на первой
        же такой таблице получал «Сначала создайте таблицу» вместо отчёта.

        Периоды при этом законны и у неготового документа: первый заводится
        вместе с самой таблицей, задолго до того, как `google_sheets_service`
        создаст Google-документ.
        """
        if await self._spreadsheets.get_by_id(spreadsheet_id, include_deleted=True) is None:
            raise NotFoundError("spreadsheet")
        return await self._periods.list_by_spreadsheet(spreadsheet_id)

    async def current(self, spreadsheet_id: int) -> Period:
        """Период, которому принадлежит сегодняшний день документа.

        Единственное чтение, которое пишет, и это осознанная плата. Строку
        текущего периода заводят только три места: создание документа, ролловер
        раз в минуту и ленивое создание на записи операции. Отсюда окно, которое
        повторяется каждый месяц: в день `reset_day`, от местной полуночи до
        ближайшего тика ролловера, `get_containing` не находит ничего —
        предыдущий период кончается ровно сегодня, а `end_date` исключительна,
        новой же строки ещё нет. Запись это чинила сама, чтение — нет, и диалог,
        которому границы периода нужны, чтобы задать вопрос, упирался бы в 404
        там, где ответ вычислим.

        Данными пользователя период при этом не является: он однозначно
        определён `reset_day` и сегодняшней датой, а `ensure` идемпотентен
        (`ON CONFLICT DO NOTHING`), так что параллельные запросы безопасны.

        Коммит здесь обязателен: сессия сама не коммитит, а репозиторий только
        делает `flush()` — без него вставка пропала бы на закрытии сессии, а
        наружу уехал бы период с `id` несуществующей строки.

        `ensure_current_period` проверяет период на закрытость, так что метод
        может отдать 422 `period_closed` там, где раньше отдавал 200. На деле
        недостижимо: ролловер закрывает только периоды, которые уже кончились.
        """
        spreadsheet = await self._get_ready(spreadsheet_id)
        period = await ensure_current_period(self._periods, spreadsheet, today_for(spreadsheet))
        await self._commit()
        return period

    async def daily_totals(
        self,
        spreadsheet_id: int,
        period_id: int | None = None,
    ) -> list[CategoryDailyTotal]:
        """Дневные итоги по категориям за период; без `period_id` — за текущий.

        Из этого строится лист статистики: по строке на категорию и по колонке на
        день периода. Суммы знаковые и в `Decimal` — округлять их нельзя нигде по
        дороге к листу.

        Всё сведено к одной валюте, :data:`api.core.constants.STATISTICS_CURRENCY`:
        складывать динары с евро бессмысленно, а лист статистики именно
        складывает. Операции в других валютах приводятся по курсу на свой день,
        и курсы для этого сначала догружаются в кэш. Порядок обязателен:
        пропущенный курс не даёт ошибки в SQL — он даёт `NULL`, который `SUM`
        молча выбрасывает, и итог занижается ровно на эту операцию.
        """
        spreadsheet = await self._get_ready(spreadsheet_id)
        period = await resolve_period(self._periods, spreadsheet, period_id)
        if period is None or period.id is None:
            return []

        base = constants.STATISTICS_CURRENCY
        await self._rates.ensure(await self._records.statistics_requirements(period.id, base))
        return await self._records.daily_totals_by_category(period.id, base=base)
