"""ORM-модель сохранённого чека."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import CHECK_KIND
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import CheckKind


class CheckORM(PkMixin, TimestampMixin, Base):
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

    `raw_payload` заполнен всегда: чек сохраняется только после успешной
    расшифровки. Отказ внешнего сервиса — ошибка пользователю, а не строка со
    статусом «дозаберём потом»; иначе к разбору пришлось бы прикручивать
    обработку неполных чеков, которых в норме не бывает.
    """

    __tablename__ = "checks"
    __table_args__ = (
        UniqueConstraint(
            "spreadsheet_id",
            "kind",
            "external_key",
            name="uq_checks_spreadsheet_id_kind_external_key",
        ),
        Index("ix_checks_spreadsheet_id", "spreadsheet_id", "id"),
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
