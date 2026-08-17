"""Сверка скелета документа: сам документ, его листы и доступы.

Выполняется один раз за тик на документ и предшествует любой его задаче. Отсюда
свойство, ради которого это и сделано: перерисовке никогда не приходится
проверять, существует ли лист, — к моменту её запуска он существует. Удалённая
пользователем вкладка восстанавливается сама, а не требует вмешательства.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

from google_sheets_service import constants
from google_sheets_service.exceptions import GoogleApiError, SheetStructureError
from google_sheets_service.google.drive_client import GoogleDriveClient
from google_sheets_service.google.sheets_client import GoogleSheetsClient, SheetProperties
from google_sheets_service.logging import get_logger
from google_sheets_service.main_api import ApiGateway
from google_sheets_service.main_api.dto import Period, SheetMapping, Spreadsheet
from google_sheets_service.sheets import layouts, requests
from google_sheets_service.sheets.layout import SheetLayout

logger = get_logger(__name__)

#: Описание листа для создания: заголовок, раскладка, адресат, период.
type SheetPlan = tuple[str, SheetLayout, str, int | None]


def _catalogue_plan() -> list[SheetPlan]:
    """Листы справочников — те, что есть у документа всегда и без периода.

    Общие для двух мест: они заводятся вместе с документом, и они же
    проверяются каждой сверкой.
    """
    return [
        (constants.CATEGORIES_SHEET_TITLE, layouts.CATEGORIES_LAYOUT, "CATEGORIES", None),
        (constants.BILLS_SHEET_TITLE, layouts.BILLS_LAYOUT, "BILLS", None),
    ]


@dataclass
class DocumentState:
    """Готовый к работе документ: его листы и где они лежат.

    Собирается сверкой и живёт до конца тика. Все задачи одного документа
    пользуются им, не переспрашивая Google.
    """

    spreadsheet: Spreadsheet
    periods: list[Period]
    mappings: dict[tuple[str, int | None], SheetMapping] = field(default_factory=dict)
    sheets: dict[int, SheetProperties] = field(default_factory=dict)

    @property
    def google_id(self) -> str:
        """Идентификатор документа в Google. К этому моменту он есть всегда."""
        assert self.spreadsheet.google_spreadsheet_id is not None
        return self.spreadsheet.google_spreadsheet_id

    def mapping(self, target: str, period_id: int | None = None) -> SheetMapping:
        """Соответствие для адресата.

        Отсутствие означает несогласованность сверки с задачей, а не ошибку
        пользователя: сверка обязана была создать лист прежде, чем задача до
        него добралась.
        """
        found = self.mappings.get((target, period_id))
        if found is None:
            raise SheetStructureError(
                f"Лист {target} (период {period_id}) не найден после сверки скелета"
            )
        return found

    def row_count(self, sheet_id: int) -> int:
        """Высота сетки листа. Ноль, если лист только что создан и не прочитан."""
        properties = self.sheets.get(sheet_id)
        return 0 if properties is None else properties.row_count

    def period(self, period_id: int) -> Period:
        """Период по идентификатору."""
        for item in self.periods:
            if item.id == period_id:
                return item
        raise SheetStructureError(f"Период {period_id} не найден в документе")


class StructureSynchronizer:
    """Доводит документ до состояния, в котором его можно рисовать."""

    def __init__(
        self,
        *,
        api: ApiGateway,
        sheets: GoogleSheetsClient,
        drive: GoogleDriveClient,
    ) -> None:
        self._api = api
        self._sheets = sheets
        self._drive = drive

    async def ensure(
        self,
        spreadsheet_id: int,
        *,
        required_period_ids: Collection[int] = (),
    ) -> DocumentState:
        """Сверяет документ и возвращает его состояние.

        `required_period_ids` — периоды, по которым в этом проходе есть работа.
        Их листы должны существовать, даже если период уже закрыт: ролловер
        напоследок перерисовывает закончившийся месяц, и если пользователь
        успел удалить его вкладку, задаче иначе некуда писать.
        """
        spreadsheet = await self._api.spreadsheets.get(spreadsheet_id)
        if spreadsheet.google_spreadsheet_id is None:
            spreadsheet = await self._create_document(spreadsheet)

        state = DocumentState(
            spreadsheet=spreadsheet,
            periods=await self._api.periods.list_all(spreadsheet_id),
        )
        state.mappings = {
            mapping.key: mapping
            for mapping in await self._api.sheet_mappings.list_by_spreadsheet(spreadsheet_id)
        }
        state.sheets = {
            properties.sheet_id: properties
            for properties in await self._sheets.get_layout(state.google_id)
        }

        await self._drop_vanished_mappings(state)
        await self._create_missing_sheets(state, set(required_period_ids))
        await self._grant_accesses(state)
        return state

    async def _create_document(self, spreadsheet: Spreadsheet) -> Spreadsheet:
        """Создаёт Google-документ и привязывает его к учётной таблице.

        Перед созданием документ ищется в Drive по метке. Без этого поиска
        потерянный ответ `POST /google-id` приводил бы к тому, что повтор задачи
        заводит второй документ, а первый — уже расшаренный пользователю —
        остаётся сиротой, о которой система больше не знает. Именно этим болела
        старая версия, создававшая таблицу до записи в базу.

        Метку даёт `Spreadsheet.drive_marker`, а не идентификатор строки: по
        одному `id` пересозданная база опознавала «своим» документ от прежнего
        запуска и привязывала его вместо создания нового.

        Листы справочников заводятся **сразу**, в теле создания. Документ без
        явного списка листов Google создаёт со своим «Лист1» на тысячу строк и
        двадцать шесть колонок; в `sheet_mappings` его нет, удалять чужие листы
        сверка не должна, и он остался бы первой вкладкой навсегда.
        """
        marker = spreadsheet.drive_marker
        existing = await self._drive.find_by_app_property(
            constants.DRIVE_APP_PROPERTY_KEY, marker
        )
        if existing is not None:
            logger.info("Документ %s уже создан в Google (%s), привязываем", spreadsheet.id,
                        existing)
            return await self._api.spreadsheets.set_google_id(spreadsheet.id, existing)

        google_id, _ = await self._sheets.create_spreadsheet(
            spreadsheet.title,
            locale=constants.SPREADSHEET_LOCALE,
            sheets=[
                {"properties": requests.sheet_properties(title, layout)}
                for title, layout, _, _ in _catalogue_plan()
            ],
        )
        # Метка ставится сразу после создания и до всего остального: если
        # процесс умрёт прямо здесь, следующая попытка найдёт документ по ней и
        # не создаст второй. Листы, оформление и записи о них доведёт обычная
        # сверка — она умеет подхватывать листы, уже существующие в документе.
        await self._drive.set_app_property(google_id, constants.DRIVE_APP_PROPERTY_KEY, marker)
        logger.info("Создан Google-документ %s для таблицы %s", google_id, spreadsheet.id)
        return await self._api.spreadsheets.set_google_id(spreadsheet.id, google_id)

    async def _drop_vanished_mappings(self, state: DocumentState) -> None:
        """Забывает листы, которых больше нет в документе.

        Пользователь может удалить вкладку. Соответствие на неё указывает в
        пустоту, и перерисовка по нему получила бы отказ Google на каждой
        попытке. Запись выбрасывается из состояния тика, лист создаётся заново,
        а `upsert` заменит её на актуальную.
        """
        vanished = [
            key for key, mapping in state.mappings.items()
            if mapping.google_sheet_id not in state.sheets
        ]
        for key in vanished:
            logger.warning(
                "Лист %s документа %s удалён из Google, создаём заново",
                key,
                state.spreadsheet.id,
            )
            del state.mappings[key]

    async def _create_missing_sheets(
        self,
        state: DocumentState,
        required_period_ids: set[int],
    ) -> None:
        """Доводит документ до полного набора листов.

        Лист, уже существующий в документе под нужным заголовком, не создаётся
        заново, а подхватывается: иначе повтор после сбоя между созданием листа
        и записью о нём упирался бы в отказ Google — заголовки листов
        уникальны, и такой документ было бы нечем починить.
        """
        plan = self._plan_sheets(state, required_period_ids)
        if not plan:
            return

        by_title = {sheet.title: sheet for sheet in state.sheets.values()}
        to_create = [item for item in plan if item[0] not in by_title]

        replies = await self._sheets.batch_update(
            state.google_id,
            [requests.create_sheet_request(title, layout) for title, layout, _, _ in to_create],
        )
        if len(replies) != len(to_create):
            # Google возвращает столько же ответов, сколько было запросов.
            # Расхождение означает, что часть листов создана и неучтена, и
            # молча обрезать `zip` нельзя: соответствие уехало бы на чужой лист.
            raise SheetStructureError(
                f"Создано листов {len(replies)} из {len(to_create)} запрошенных"
            )

        created = {
            title: int(reply["addSheet"]["properties"]["sheetId"])
            for reply, (title, _, _, _) in zip(replies, to_create, strict=True)
        }

        for title, layout, target, period_id in plan:
            existing = by_title.get(title)
            sheet_id = created[title] if existing is None else existing.sheet_id
            protections = () if existing is None else existing.protected_range_ids

            await self._sheets.batch_update(
                state.google_id,
                requests.header_requests(
                    sheet_id, layout, existing_protection_ids=protections
                ),
            )
            mapping = await self._api.sheet_mappings.upsert(
                state.spreadsheet.id,
                target=target,
                google_sheet_id=sheet_id,
                title=title,
                period_id=period_id,
            )
            state.mappings[mapping.key] = mapping
            state.sheets[sheet_id] = SheetProperties(
                sheet_id=sheet_id,
                title=title,
                row_count=(
                    constants.GRID_INITIAL_ROWS if existing is None else existing.row_count
                ),
                # Ширина сетки, а не раскладки: поле зеркалит `gridProperties`
                # Google, а там за системными колонками стоит запас.
                column_count=layout.grid_column_count,
            )
            logger.info(
                "%s лист «%s» документа %s",
                "Создан" if existing is None else "Подхвачен",
                title,
                state.spreadsheet.id,
            )

    def _plan_sheets(
        self,
        state: DocumentState,
        required_period_ids: set[int],
    ) -> list[tuple[str, SheetLayout, str, int | None]]:
        """Составляет список листов, которых не хватает.

        Период получает листы, если он открыт **или** по нему есть работа в этом
        проходе. Одних открытых мало: ролловер, закрывая месяц, напоследок
        перерисовывает его — пользователь мог добавить операцию в последние
        минуты. Удали он к тому времени вкладку, задача не нашла бы листа и
        падала бы вечно, а терминальной такая ошибка не считается.

        Периоды, о которых никто не спрашивал, листов по-прежнему не получают:
        иначе документ, привязанный спустя годы, оброс бы пустыми вкладками за
        всю историю.
        """
        plan: list[SheetPlan] = [
            item for item in _catalogue_plan() if (item[2], None) not in state.mappings
        ]

        for period in state.periods:
            if not period.is_open and period.id not in required_period_ids:
                continue
            if ("OPERATIONS", period.id) not in state.mappings:
                plan.append(
                    (
                        layouts.operations_sheet_title(period.start_date),
                        layouts.OPERATIONS_LAYOUT,
                        "OPERATIONS",
                        period.id,
                    )
                )
            if ("STATISTICS", period.id) not in state.mappings:
                plan.append(
                    (
                        layouts.statistics_sheet_title(period.start_date),
                        layouts.statistics_layout(period.start_date, period.end_date),
                        "STATISTICS",
                        period.id,
                    )
                )
            if ("CHECKS", period.id) not in state.mappings:
                plan.append(
                    (
                        layouts.checks_sheet_title(period.start_date),
                        layouts.CHECKS_LAYOUT,
                        "CHECKS",
                        period.id,
                    )
                )
        return plan

    async def _grant_accesses(self, state: DocumentState) -> None:
        """Выдаёт доступы, которые ещё не выданы.

        Отказ по конкретной почте не прерывает сверку: одна опечатка в адресе
        иначе навечно заблокировала бы создание листов новых месяцев. Api
        удаляет такую запись и сообщает об этом пользователю, а сверка идёт
        дальше.
        """
        pending = await self._api.spreadsheets.list_pending_accesses(state.spreadsheet.id)
        for access in pending:
            try:
                await self._drive.grant_access(
                    state.google_id, access.email, role=access.role.lower()
                )
            except GoogleApiError as error:
                if not error.terminal:
                    raise
                logger.warning(
                    "Доступ для %s документа %s не выдан: %s",
                    access.email,
                    state.spreadsheet.id,
                    error.message,
                )
                await self._api.spreadsheets.mark_access_failed(
                    state.spreadsheet.id, access.id
                )
                continue
            await self._api.spreadsheets.mark_access_granted(state.spreadsheet.id, access.id)
            logger.info("Выдан доступ %s к документу %s", access.email, state.spreadsheet.id)
