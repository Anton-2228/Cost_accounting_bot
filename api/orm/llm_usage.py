"""ORM-модель одного обращения к модели: токены, стоимость, повод."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base
from api.db.column_types import LLM_COST, LLM_ENTITY_KIND, LLM_OPERATION
from api.db.mixins import PkMixin, TimestampMixin
from api.enums import LlmEntityKind, LlmOperation


class LlmUsageORM(PkMixin, TimestampMixin, Base):
    """Сколько стоило одно обращение к модели.

    Таблица отвечает ровно на один вопрос — сколько денег ушло и на что, — и
    состоит только из того, что на этот вопрос работает. Ни статуса, ни попыток,
    ни текстов промптов здесь нет: записываются лишь состоявшиеся вызовы,
    ответ которых удалось разобрать.

    `model` — модель, которую **вернул провайдер**, а не та, что была
    запрошена. Через OpenRouter это не одно и то же: маршрутизация может отдать
    ответ другой модели, и счёт придёт именно за неё.

    `cost` допускает NULL: стоимость приезжает от провайдера, а не считается по
    своему прайс-листу, и её может не быть — другой `base_url`, старый ответ.
    Пусто означает «неизвестно» и обязано отличаться от нуля, иначе сумма за
    месяц тихо занижалась бы ровно на неизвестное.

    `raw_usage` хранит блок `usage` целиком, как `checks.raw_payload` хранит
    расшифровку. Провайдеры отдают заметно больше трёх счётчиков —
    кэшированные токены, reasoning, свои расширения, — и заводить колонку под
    каждое поле значило бы ходить в миграцию всякий раз, когда провайдер
    что-нибудь добавит.

    Пара `entity_kind` + `entity_id` — намеренно не внешний ключ. Модель
    зовётся при разборе чека, когда ни одной операции реестра ещё не
    существует, и одно обращение покрывает сразу все позиции: ссылка на
    `records` была бы неверной по кратности. Пара необязательна целиком —
    `CHECK` следит, чтобы заполнены были обе колонки или ни одной, потому что
    «вид без идентификатора» не значит ничего.

    Строки не удаляются никогда, в том числе вместе с документом: отвязывание
    документа мягкое, и каскад по `spreadsheet_id` больше не срабатывает.
    Деньги потрачены независимо от того, ведёт ли пользователь учёт дальше.
    """

    __tablename__ = "llm_usages"
    __table_args__ = (
        CheckConstraint(
            "(entity_kind IS NULL) = (entity_id IS NULL)",
            name="entity_pair",
        ),
        # Единственная выборка, ради которой таблица существует: «сколько ушло
        # за период». Документ первым — сводка по одному документу считается
        # чаще, чем по всем сразу.
        Index("ix_llm_usages_spreadsheet_id_created_at", "spreadsheet_id", "created_at"),
    )

    spreadsheet_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("spreadsheets.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[LlmOperation] = mapped_column(LLM_OPERATION, nullable=False)
    #: Вид сущности, о которой спрашивали. Без внешнего ключа — см. класс.
    entity_kind: Mapped[LlmEntityKind | None] = mapped_column(
        LLM_ENTITY_KIND,
        nullable=True,
        default=None,
    )
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    #: Модель в том виде, в каком её назвал провайдер.
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Стоимость в валюте провайдера. Пусто — провайдер её не прислал.
    cost: Mapped[Decimal | None] = mapped_column(LLM_COST, nullable=True, default=None)
    #: Блок `usage` ответа целиком, без обрезки и приведения типов.
    raw_usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
