"""Сохранение чеков, кэш «товар → тип» и запись разобранного чека."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import constants
from api.core.logging import get_logger
from api.domain.cashed_record import CashedRecord
from api.domain.category import Category
from api.domain.check import Check
from api.domain.check_item import CheckItem, ProductTypeAssignment
from api.domain.record import Record
from api.enums import CategoryKind, CheckKind, Currency, SheetTarget, SyncTaskKind
from api.exceptions.base import BusinessRuleError, ConflictError, NotFoundError
from api.repositories.cashed_record_repository import CashedRecordRepository
from api.repositories.category_repository import CategoryRepository
from api.repositories.check_repository import CheckRepository
from api.repositories.period_repository import PeriodRepository
from api.repositories.record_repository import RecordRepository
from api.repositories.sheet_sync_task_repository import SheetSyncTaskRepository, TaskKey
from api.repositories.source_repository import SourceRepository
from api.repositories.spreadsheet_repository import SpreadsheetRepository
from api.services._periods import ensure_current_period, today_for
from api.services.base import BaseSpreadsheetService

logger = get_logger(__name__)

#: Причина конфликта: этот чек в документе уже есть. Отдаётся отдельно от общего
#: «нарушено ограничение целостности», потому что для сканирующего это не
#: ошибка, а осмысленный ответ «уже добавлен».
ALREADY_SAVED_REASON = "check_already_saved"

#: Причина конфликта: чек уже разобран. Возникает, когда разбор запущен дважды
#: (два устройства, повтор запроса) — операции уже в реестре, и повторная запись
#: удвоила бы их.
ALREADY_PROCESSED_REASON = "check_already_processed"

#: Причина конфликта: тип товара уже закреплён за другой категорией документа.
#: `UNIQUE (spreadsheet_id, product_type)` делает это состояние невыразимым, но
#: молчаливое переназначение было бы хуже отказа: раскладка позиций чека стала
#: бы зависеть от порядка обработки.
TYPE_TAKEN_REASON = "product_type_taken"

#: Валюта чека по его формату. Не спрашивается у пользователя и не извлекается
#: из расшифровки: каждый из форматов привязан к своей стране и своей валюте, и
#: «валюта чека» для него не переменная, а свойство формата. Чек ФНС физически
#: рублёвый — суммы в нём приходят целыми копейками; сербский так же жёстко
#: динарный. Зеркало `_CHECK_CURRENCY` в `telegram_bot.checks.models`, где по
#: этой же причине валюта проставляется разобранному чеку.
_CHECK_CURRENCY: dict[CheckKind, Currency] = {
    CheckKind.RU_FNS: Currency.RUB,
    CheckKind.SRB_SUF: Currency.RSD,
}


class CheckService(BaseSpreadsheetService):
    """Хранение сырья чека и запись уже разобранного чека.

    Две половины одного пути, разнесённые во времени. Сначала `save`: чек
    приезжает от Mini App расшифрованным, и в БД ложится только сырьё —
    QR-строка, вид формата и ответ внешнего сервиса целиком. Затем разбор,
    который доводится вне api (модель, стадии диалога, подтверждения
    пользователя перемежаются вопросами и живут в состоянии клиента), а сюда
    приезжает готовый результат `commit_check` — и записывается **одной
    транзакцией**, иначе прерывание на середине оставило бы половину чека в
    реестре, а половину потеряло.
    """

    def __init__(
        self,
        session: AsyncSession,
        spreadsheets: SpreadsheetRepository,
        *,
        periods: PeriodRepository,
        categories: CategoryRepository,
        sources: SourceRepository,
        records: RecordRepository,
        cashed_records: CashedRecordRepository,
        checks: CheckRepository,
        tasks: SheetSyncTaskRepository,
    ) -> None:
        super().__init__(session, spreadsheets)
        self._periods = periods
        self._categories = categories
        self._sources = sources
        self._records = records
        self._cashed_records = cashed_records
        self._checks = checks
        self._tasks = tasks

    # --- сохранение ---

    async def list_checks(
        self,
        spreadsheet_id: int,
        *,
        unprocessed: bool = False,
        period_id: int | None = None,
    ) -> list[Check]:
        """Сохранённые чеки документа в порядке поступления.

        `unprocessed=True` отдаёт очередь разбора — только то, что ещё ждёт.

        `period_id` отдаёт архив месяца: разобранные чеки, чьи операции попали
        в этот период. Оба фильтра вместе бессмысленны — неразобранный чек
        операций не имеет, — и одновременная передача отвергается как ошибка
        вызывающего, а не молча возвращает пустой список.
        """
        await self._get(spreadsheet_id)
        if period_id is not None:
            if unprocessed:
                raise BusinessRuleError("Фильтры `unprocessed` и `period_id` несовместимы")
            return await self._checks.list_processed_for_period(spreadsheet_id, period_id)
        return await self._checks.list_by_spreadsheet(spreadsheet_id, unprocessed=unprocessed)

    async def delete_check(self, spreadsheet_id: int, check_id: int) -> None:
        """Мягко удаляет неразобранный чек.

        Удаление мягкое, как и всюду в таблице: два механизма удаления на одну
        строку значили бы два разных ответа на вопрос «что стало с чеком».
        Сырьё остаётся, из всех выборок чек пропадает, а ту же бумажку
        разрешено отсканировать заново — уникальность ключа частичная и живых
        строк с ним больше нет.

        Разобранный чек этим путём не убрать — 409. Он уходит следом за своими
        операциями (`RecordService.delete`), и заводить второй вход в то же
        состояние незачем: пользователь, удаливший чек, но не его операции,
        получил бы реестр со строками из ниоткуда.
        """
        await self._get(spreadsheet_id)
        check = await self._checks.get_for_spreadsheet(check_id, spreadsheet_id)
        if check is None:
            raise NotFoundError("check")
        if check.processed_at is not None:
            raise ConflictError(
                "Чек уже разобран",
                details={"reason": ALREADY_PROCESSED_REASON},
            )

        assert check.id is not None
        await self._checks.soft_delete(check.id, at=datetime.now(UTC))
        await self._commit()
        logger.info("Чек %s удалён из документа %s", check_id, spreadsheet_id)

    async def save(
        self,
        spreadsheet_id: int,
        *,
        kind: CheckKind,
        qr_raw: str,
        external_key: str,
        raw_payload: dict[str, Any],
        fetched_at: datetime,
    ) -> Check:
        """Сохраняет расшифрованный чек целиком.

        Готовность Google-таблицы не проверяется: сканирующему незачем знать,
        дорисован ли документ, — чек полежит и дождётся разбора.

        Дубль ловится дважды. Предварительная проверка нужна, чтобы ответить
        внятной причиной, а `IntegrityError` — потому что между ней и вставкой
        помещается второй такой же скан: без перехвата гонка двух телефонов
        (или двойного нажатия) отвечала бы пятисоткой.
        """
        await self._get(spreadsheet_id)

        existing = await self._checks.get_by_external_key(spreadsheet_id, kind, external_key)
        if existing is not None:
            raise ConflictError("Чек уже добавлен", details={"reason": ALREADY_SAVED_REASON})

        check = Check(
            spreadsheet_id=spreadsheet_id,
            kind=kind,
            qr_raw=qr_raw,
            external_key=external_key,
            raw_payload=raw_payload,
            fetched_at=fetched_at,
        )
        try:
            saved = await self._checks.add(check)
            await self._commit()
        except IntegrityError as error:
            # Сессия после нарушения ограничения непригодна: без отката любой
            # следующий запрос в ней получил бы PendingRollbackError.
            await self._session.rollback()
            raise ConflictError(
                "Чек уже добавлен",
                details={"reason": ALREADY_SAVED_REASON},
            ) from error

        logger.info("Сохранён чек %s (%s) в документ %s", saved.id, kind, spreadsheet_id)
        return saved

    # --- кэш ---

    async def list_cashed_records(self, spreadsheet_id: int) -> list[CashedRecord]:
        """Выученные соответствия «товар → тип» документа."""
        await self._get_ready(spreadsheet_id)
        return await self._cashed_records.list_by_spreadsheet(spreadsheet_id)

    # --- запись чека ---

    async def commit_check(
        self,
        spreadsheet_id: int,
        *,
        check_id: int,
        source_id: int,
        items: Sequence[CheckItem],
        new_product_types: Sequence[ProductTypeAssignment] = (),
    ) -> list[Record]:
        """Записывает разобранный чек: типы товаров, кэш, операции, отметку.

        Всё перечисленное — одна транзакция. Порядок внутри значения не имеет,
        важно лишь то, что ни одна её часть не может уцелеть без остальных.
        Отметка `processed_at` — такая же часть: уцелей операции без неё, чек
        вернулся бы в очередь и был бы записан второй раз.

        Валюта операций берётся из формата чека, а не из его расшифровки и не у
        пользователя: см. :data:`_CHECK_CURRENCY`.
        """
        spreadsheet = await self._get_ready(spreadsheet_id)
        check = await self._checks.get_for_spreadsheet(check_id, spreadsheet_id)
        if check is None:
            raise NotFoundError("check")
        if check.processed_at is not None:
            raise ConflictError(
                "Чек уже разобран",
                details={"reason": ALREADY_PROCESSED_REASON},
            )
        if await self._sources.get_for_spreadsheet(source_id, spreadsheet_id) is None:
            raise NotFoundError("source")

        # Все категории документа, а не только активные: неактивная категория
        # скрыта из подсказок, но продолжает существовать, и позиция чека,
        # разложенная в неё до того, как её скрыли, не должна валить запись
        # всего чека целиком.
        categories = {
            category.id: category
            for category in await self._categories.list_by_spreadsheet(spreadsheet_id)
            if category.id is not None
        }
        await self._assign_product_types(spreadsheet_id, new_product_types, categories)

        today = today_for(spreadsheet)
        period = await ensure_current_period(self._periods, spreadsheet, today)
        assert period.id is not None

        currency = _CHECK_CURRENCY[check.kind]

        created: list[Record] = []
        for item in items:
            category = categories.get(item.category_id)
            if category is None:
                raise NotFoundError("category")

            signed = item.amount if category.kind is CategoryKind.INCOME else -item.amount
            created.append(
                await self._records.add(
                    Record(
                        spreadsheet_id=spreadsheet_id,
                        period_id=period.id,
                        category_id=item.category_id,
                        source_id=source_id,
                        amount=signed,
                        currency=currency,
                        added_at=today,
                        product_name=item.product_name,
                        product_type=item.product_type,
                        check_id=check_id,
                    )
                )
            )
            if item.product_type:
                await self._cashed_records.upsert(
                    CashedRecord(
                        spreadsheet_id=spreadsheet_id,
                        product_name=item.product_name,
                        product_type=item.product_type,
                    )
                )

        marked = await self._checks.mark_processed(check_id, at=datetime.now(UTC))
        if marked is None:
            # Между проверкой выше и этим местом чек успел разобрать кто-то ещё.
            # Тот же ответ, что и по предварительной проверке: операции этой
            # транзакции откатятся, а уже записанные останутся на месте.
            await self._session.rollback()
            raise ConflictError(
                "Чек уже разобран",
                details={"reason": ALREADY_PROCESSED_REASON},
            )

        keys: list[TaskKey] = [
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.OPERATIONS, period.id),
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.STATISTICS, period.id),
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.CHECKS, period.id),
            (spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.BILLS, None),
        ]
        if new_product_types:
            keys.append((spreadsheet_id, SyncTaskKind.REDRAW, SheetTarget.CATEGORIES, None))
        await self._tasks.enqueue_many(keys)

        await self._commit()
        logger.info(
            "Чек %s из %s позиций записан в документ %s",
            check_id,
            len(created),
            spreadsheet_id,
        )
        return created

    async def _assign_product_types(
        self,
        spreadsheet_id: int,
        assignments: Sequence[ProductTypeAssignment],
        categories: Mapping[int, Category],
    ) -> None:
        """Закрепляет новые типы товаров за категориями.

        Категория по умолчанию для расходов типов не получает никогда: это
        корзина для всего, что не удалось разложить, и обучение на её
        содержимом притянуло бы туда же следующие чеки.

        Занятый тип ловится дважды. Предварительная проверка нужна, чтобы
        назвать чужую категорию: пользователь должен знать, куда уже отнесена
        «молочка», иначе отказ выглядит беспричинным. `IntegrityError` — потому
        что между проверкой и вставкой помещается импорт справочника из листа,
        который закрепляет тот же тип за другой категорией.
        """
        for assignment in assignments:
            category = categories.get(assignment.category_id)
            if category is None:
                raise NotFoundError("category")
            if category.title == constants.DEFAULT_EXPENSE_CATEGORY:
                continue

            owner = await self._categories.find_by_product_type(
                spreadsheet_id, assignment.product_type
            )
            if owner is not None and owner.id != assignment.category_id:
                await self._session.rollback()
                raise self._type_taken(assignment.product_type, owner.title)

            try:
                await self._categories.add_product_type(
                    assignment.category_id, assignment.product_type
                )
            except IntegrityError as error:
                # Сессия после нарушения ограничения непригодна: без отката
                # любой следующий запрос в ней получил бы PendingRollbackError.
                await self._session.rollback()
                raise self._type_taken(assignment.product_type, None) from error

    @staticmethod
    def _type_taken(product_type: str, category_title: str | None) -> ConflictError:
        """Собирает отказ «тип уже закреплён за другой категорией»."""
        details: dict[str, Any] = {
            "reason": TYPE_TAKEN_REASON,
            "product_type": product_type,
        }
        if category_title is not None:
            details["category"] = category_title
        return ConflictError(
            f"Тип «{product_type}» уже закреплён за другой категорией",
            details=details,
        )
