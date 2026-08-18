"""ORM-модель сохранённого чека."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import CHECK_KIND
from api.db.mixins import PkMixin, SoftDeleteMixin, TimestampMixin
from api.enums import CheckKind


class CheckORM(PkMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Чек целиком в том виде, в каком он приехал: QR-строка и расшифровка.

    Ни даты, ни суммы, ни валюты отдельными колонками здесь нет намеренно.
    Форматов чеков будет больше одного (сегодня ФНС, завтра сербский
    фискальный), и у каждого свои реквизиты и своя структура ответа внешнего
    сервиса. Колонка, названная «сумма», означала бы, что мы уже выбрали, чью
    сумму считать настоящей, — а выбирать это можно только на разборе, зная
    формат. Поэтому таблица хранит сырьё и вид, а интерпретация откладывается.

    `external_key` вычисляет парсер формата (для ФНС — «ФН:ФД:ФП»). Уникальность
    `(spreadsheet_id, kind, external_key)` делает повторное добавление того же
    чека невыразимым состоянием, при том что БД не знает ни одного формата.
    Уникальность **частичная**, среди живых строк: жить может только один
    экземпляр бумажки, а сколько их было в истории документа — не ограничено.
    Иначе однажды удалённый чек занимал бы ключ навсегда и ту же бумажку нельзя
    было бы отсканировать заново.

    `raw_payload` заполнен всегда: чек сохраняется только после успешной
    расшифровки. Отказ внешнего сервиса — ошибка пользователю, а не строка со
    статусом «дозаберём потом»; иначе к разбору пришлось бы прикручивать
    обработку неполных чеков, которых в норме не бывает.

    `processed_at` — единственный признак того, что чек разобран. Отдельного
    статуса нет намеренно: разбор либо записал операции и проставил метку одной
    транзакцией, либо не сделал ни того, ни другого. Промежуточных значений,
    которые пришлось бы чинить руками, не существует.

    Удаление **мягкое**, как у операций. Физическое стёрло бы `raw_payload` —
    единственный след покупки в системе; к тому же операции, вышедшие из чека,
    удаляются мягко и продолжают на него ссылаться, а строка, на которую
    ссылаются, обязана существовать. Чек умирает вслед за последней своей живой
    операцией (`RecordService.delete`) — и по `/check_del`, пока не разобран.
    """

    __tablename__ = "checks"
    __table_args__ = (
        # Уникальность частичная, поэтому индекс, а не констрейнт: `UNIQUE` без
        # условия распространялся бы и на удалённые чеки.
        Index(
            "uq_checks_spreadsheet_id_kind_external_key",
            "spreadsheet_id",
            "kind",
            "external_key",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        # Данные это не ограничивает: id уже первичный ключ. Констрейнт нужен,
        # чтобы стал возможен составной внешний ключ `records → checks`:
        # PostgreSQL требует UNIQUE ровно по тому набору колонок, на который
        # ссылается FK. Ровно как у `periods`.
        UniqueConstraint("id", "spreadsheet_id", name="uq_checks_id_spreadsheet_id"),
        Index("ix_checks_spreadsheet_id", "spreadsheet_id", "id"),
        # Очередь разбора: «самый старый неразобранный чек документа». Индекс
        # партиальный, потому что разобранные чеки в этой выборке не нужны
        # никогда, а их со временем становится большинство. Удалённые — тем
        # более: очередь не должна показывать то, чего в документе больше нет.
        Index(
            "ix_checks_unprocessed",
            "spreadsheet_id",
            "id",
            postgresql_where="processed_at IS NULL AND deleted_at IS NULL",
        ),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[CheckKind] = mapped_column(CHECK_KIND, nullable=False)
    #: Строка ровно так, как её отдал сканер: она и есть первоисточник.
    qr_raw: Mapped[str] = mapped_column(Text, nullable=False)
    #: Ключ дедупликации в терминах формата.
    external_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: Ответ внешнего сервиса целиком, без обрезки и приведения типов.
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: Когда расшифровка была получена. От `created_at` отличается тем, что
    #: относится к внешнему сервису, а не к строке в нашей таблице.
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Когда чек был разобран в операции реестра. Пусто — чек ждёт разбора.
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
