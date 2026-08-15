"""Движок: один проход по очереди задач."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from time import monotonic
from typing import Any

from google_sheets_service.exceptions import SyncError
from google_sheets_service.google.sheets_client import GoogleSheetsClient
from google_sheets_service.logging import get_logger
from google_sheets_service.main_api import ApiGateway
from google_sheets_service.main_api.dto import SyncTask
from google_sheets_service.sync.importer import SheetImporter
from google_sheets_service.sync.pacer import Pacer
from google_sheets_service.sync.redraw import SheetRedrawer
from google_sheets_service.sync.structure import DocumentState, StructureSynchronizer

logger = get_logger(__name__)

#: Порядок разбора задач одного документа. `STRUCTURE` первой: она создаёт
#: листы, без которых остальным некуда писать. `IMPORT` последним: он читает
#: лист, и делать это следует после того, как перерисовки уложили туда
#: актуальные идентификаторы.
_TARGET_ORDER = {
    "STRUCTURE": 0,
    "CATEGORIES": 1,
    "BILLS": 2,
    "OPERATIONS": 3,
    "STATISTICS": 4,
}


@dataclass
class TickReport:
    """Итог одного прохода. Отдаётся в `/health` — это вся наблюдаемость сервиса."""

    status: str = "ok"
    claimed: int = 0
    completed: int = 0
    failed: int = 0
    #: Задачи, которые выполнены, но за время работы устарели снова. Не ошибка:
    #: пользователь успел что-то поменять, и лист будет перерисован ещё раз.
    restaged: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Представление для ответа `/health`."""
        return asdict(self)

    def summary(self) -> str:
        """Однострочная сводка для лога."""
        return (
            f"взято={self.claimed} сделано={self.completed} "
            f"неудач={self.failed} повторно={self.restaged} "
            f"за {self.duration_seconds:.1f} с статус={self.status}"
        )


class SyncEngine:
    """Забирает пачку задач и выполняет их по одной.

    Ошибка отдельной задачи никогда не роняет проход: она уезжает в api через
    `fail`, и очередь сама решит, когда повторить. Проход целиком падает только
    на `claim` — если недоступно само api, работать всё равно не с чем.
    """

    def __init__(
        self,
        *,
        api: ApiGateway,
        sheets: GoogleSheetsClient,
        structure: StructureSynchronizer,
        redrawer: SheetRedrawer,
        importer: SheetImporter,
        pacer: Pacer,
        claim_limit: int,
    ) -> None:
        self._api = api
        self._sheets = sheets
        self._structure = structure
        self._redrawer = redrawer
        self._importer = importer
        self._pacer = pacer
        self._claim_limit = claim_limit
        self._lock = asyncio.Lock()
        self._last_report: TickReport | None = None

    @property
    def is_running(self) -> bool:
        """Проход выполняется прямо сейчас."""
        return self._lock.locked()

    @property
    def last_report(self) -> TickReport | None:
        """Итог последнего завершённого прохода."""
        return self._last_report

    async def run_once(self) -> TickReport:
        """Выполняет один проход по очереди.

        Повторный вызов во время работы возвращает отметку о пропуске, а не
        ждёт: ручной `POST /sync` и планировщик иначе выстроились бы в очередь и
        сделали одну и ту же работу дважды подряд.
        """
        if self._lock.locked():
            logger.warning("Предыдущий проход ещё идёт, пропуск")
            return TickReport(status="skipped")

        async with self._lock:
            started = monotonic()
            # Пул соединений httplib2 не проверяет живость сокета, а между
            # проходами он успевает протухнуть. Сброс здесь — единственное
            # безопасное место: активных запросов ещё нет.
            self._sheets.reset_connections()

            report = TickReport()
            tasks = await self._api.tasks.claim(self._claim_limit)
            report.claimed = len(tasks)

            for spreadsheet_id, group in _group_by_document(tasks).items():
                await self._run_document(spreadsheet_id, group, report)

            report.duration_seconds = monotonic() - started
            if report.failed:
                report.status = "failed" if not report.completed else "partial"
            self._last_report = report
            logger.info("Проход завершён: %s", report.summary())
            return report

    async def _run_document(
        self,
        spreadsheet_id: int,
        tasks: list[SyncTask],
        report: TickReport,
    ) -> None:
        """Выполняет задачи одного документа.

        Скелет сверяется один раз на документ, а не на задачу: это чтение из
        Google, и повторять его для каждого из четырёх листов значило бы
        вчетверо увеличить расход квоты без единого нового факта.

        Сверке передаются периоды, упомянутые задачами: их листы обязаны
        существовать, даже если период уже закрыт. Иначе перерисовка
        закончившегося месяца — а её ставит ролловер — не нашла бы листа, если
        пользователь успел удалить вкладку.

        Провалившаяся сверка проваливает все задачи документа: без документа и
        листов ни одна из них выполнима не будет.
        """
        required_period_ids = {task.period_id for task in tasks if task.period_id is not None}
        try:
            state = await self._structure.ensure(
                spreadsheet_id, required_period_ids=required_period_ids
            )
        except SyncError as error:
            logger.exception("Сверка документа %s не удалась", spreadsheet_id)
            for task in tasks:
                await self._report_failure(task, error, report)
            return
        except Exception as error:  # noqa: BLE001 — проход не должен падать из-за документа
            logger.exception("Сверка документа %s упала", spreadsheet_id)
            for task in tasks:
                await self._report_failure(task, error, report)
            return

        for task in tasks:
            await self._run_task(task, state, report)
            await self._pacer.pause()

    async def _run_task(self, task: SyncTask, state: DocumentState, report: TickReport) -> None:
        """Выполняет одну задачу и отчитывается о ней."""
        try:
            await self._perform(task, state)
        except SyncError as error:
            logger.exception("Задача %s (%s) не выполнена", task.id, task.target)
            await self._report_failure(task, error, report)
            return
        except Exception as error:  # noqa: BLE001 — одна задача не роняет проход
            logger.exception("Задача %s (%s) упала", task.id, task.target)
            await self._report_failure(task, error, report)
            return

        await self._api.tasks.complete(task)
        report.completed += 1

    async def _perform(self, task: SyncTask, state: DocumentState) -> None:
        """Делает то, ради чего задача создана.

        `STRUCTURE` не имеет собственного действия: всё, что ей нужно, уже
        сделала сверка скелета — она создала документ, листы и выдала доступы.
        """
        if task.kind == "IMPORT":
            await self._importer.import_sheet(state, task.target)
            return
        if task.target == "STRUCTURE":
            return
        await self._redrawer.redraw(state, task.target, task.period_id)

    async def _report_failure(
        self,
        task: SyncTask,
        error: Exception,
        report: TickReport,
    ) -> None:
        """Сообщает api о неудаче.

        Терминальность берётся у самой ошибки: её знает только тот, кто видел
        ответ Google. Неудача самого отчёта не считается: если api недоступно,
        задача останется забранной и вернётся в очередь по истечении аренды.
        """
        terminal = isinstance(error, SyncError) and error.terminal
        message = error.message if isinstance(error, SyncError) else str(error)
        report.failed += 1
        report.errors.append(f"{task.target}#{task.id}: {message}")
        try:
            await self._api.tasks.fail(task, message, terminal=terminal)
        except Exception:  # noqa: BLE001 — отчёт о неудаче не должен ронять проход
            logger.exception("Не удалось отчитаться о задаче %s", task.id)


def _group_by_document(tasks: list[SyncTask]) -> dict[int, list[SyncTask]]:
    """Группирует задачи по документам и упорядочивает внутри группы.

    Порядок внутри документа определён: сначала скелет, затем справочники,
    затем листы периодов, и только потом чтение листа обратно. Очередь порядка
    не обещает — там задачи независимы по построению, — но выполнить импорт
    раньше перерисовки значило бы прочитать лист, в котором ещё нет
    идентификаторов новых строк.
    """
    grouped: dict[int, list[SyncTask]] = {}
    for task in tasks:
        grouped.setdefault(task.spreadsheet_id, []).append(task)
    for group in grouped.values():
        group.sort(key=lambda task: (task.kind == "IMPORT", _TARGET_ORDER.get(task.target, 99)))
    return grouped
