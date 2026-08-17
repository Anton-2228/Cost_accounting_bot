"""Тесты сборки сообщений."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from telegram_bot.api_client.models import Category, Record, Source, Spreadsheet, Transfer
from telegram_bot.checks.draft import CheckDraft, DraftItem
from telegram_bot.formatting import (
    CheckFormatter,
    MoneyFormatter,
    RecordFormatter,
    TableFormatter,
    TransferFormatter,
)
from telegram_bot.parsers.results import ParsedRecord, ParsedTransfer


class TestMoneyFormatter:
    """Печать сумм."""

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            (Decimal("500.00"), "500,00 ₽"),
            (Decimal("1234.56"), "1 234,56 ₽"),
            (Decimal("1000000"), "1 000 000,00 ₽"),
            (Decimal("0.05"), "0,05 ₽"),
        ],
    )
    def test_formatting(self, amount: Decimal, expected: str) -> None:
        """Разряды разделяются, копейки не теряются."""
        assert MoneyFormatter.format(amount) == expected

    def test_sign_is_dropped(self) -> None:
        """Знак снимается: расход и так назван расходом.

        Api хранит сумму расхода отрицательной, но «-500 ₽» рядом со словом
        «расход» читается как двойное отрицание.
        """
        assert MoneyFormatter.format(Decimal("-500.00")) == "500,00 ₽"


def _record(amount: str = "-500.00") -> Record:
    """Операция из ответа api."""
    return Record(
        id=42,
        period_id=1,
        category_id=1,
        source_id=1,
        amount=Decimal(amount),
        added_at=date(2026, 8, 14),
        notes="обед",
        from_check=False,
    )


class TestRecordFormatter:
    """Сообщения об операциях."""

    def test_saved_expense(self) -> None:
        """В подтверждении есть вид, сумма, категория, счёт, дата и id."""
        parsed = ParsedRecord(
            amount=Decimal("500"),
            category_id=1,
            category_title="Продукты",
            category_is_income=False,
            source_id=1,
            source_title="Карта",
            notes="обед",
        )
        text = RecordFormatter.saved(parsed, _record())

        assert "расход" in text
        assert "500,00 ₽" in text
        assert "Продукты" in text
        assert "Карта" in text
        assert "обед" in text
        assert "id: 42" in text

    def test_saved_income_is_named_income(self) -> None:
        """Доход называется доходом: вид приходит из категории."""
        parsed = ParsedRecord(
            amount=Decimal("1000"),
            category_id=2,
            category_title="Зарплата",
            category_is_income=True,
            source_id=1,
            source_title="Карта",
            notes="",
        )
        text = RecordFormatter.saved(parsed, _record(amount="1000.00"))

        assert "доход" in text
        assert "Пометка" not in text

    def test_deleted_resolves_titles(
        self,
        categories: list[Category],
        sources: list[Source],
    ) -> None:
        """Названия берутся из уже загруженных справочников, а не запросом."""
        text = RecordFormatter.deleted(_record(), categories=categories, sources=sources)

        assert "Продукты" in text
        assert "Карта" in text
        assert "id: 42" in text

    def test_deleted_survives_missing_titles(self) -> None:
        """Удалённая из справочника категория не роняет сообщение.

        Операция ссылается на категорию, которую могли выключить и убрать из
        активных: сообщение об удалении обязано выйти в любом случае.
        """
        text = RecordFormatter.deleted(_record(), categories=[], sources=[])
        assert "id: 42" in text


class TestTransferFormatter:
    """Сообщения о переводах."""

    def _transfer(self) -> Transfer:
        return Transfer(
            id=7,
            period_id=1,
            from_source_id=2,
            to_source_id=1,
            amount=Decimal("1000.00"),
            added_at=date(2026, 8, 14),
            notes="отложил",
        )

    def test_saved(self) -> None:
        """Направление печатается стрелкой, как и в реестре таблицы."""
        parsed = ParsedTransfer(
            amount=Decimal("1000"),
            from_source_id=2,
            from_source_title="Наличные",
            to_source_id=1,
            to_source_title="Карта",
            notes="отложил",
        )
        text = TransferFormatter.saved(parsed, self._transfer())

        assert "Наличные → Карта" in text
        assert "1 000,00 ₽" in text
        assert "id: 7" in text

    def test_deleted(self, sources: list[Source]) -> None:
        """Удаление называет оба счёта."""
        text = TransferFormatter.deleted(self._transfer(), sources=sources)
        assert "Наличные → Карта" in text


class TestTableFormatter:
    """Ссылка на документ."""

    def test_ready_table_gives_link(self) -> None:
        """Адрес собирается из идентификатора документа."""
        spreadsheet = Spreadsheet(
            id=1,
            google_spreadsheet_id="abc123",
            title="Мои расходы",
            reset_day=15,
            timezone="Europe/Moscow",
        )
        text = TableFormatter.link(spreadsheet)

        assert "https://docs.google.com/spreadsheets/d/abc123" in text
        assert "Мои расходы" in text

    def test_not_ready_table_explains_waiting(self) -> None:
        """Пока документа нет — объяснение, а не пустая ссылка.

        Это рабочее состояние сразу после `/start`: строки в базе созданы, а
        документ создаёт отдельный сервис по задаче из очереди.
        """
        spreadsheet = Spreadsheet(
            id=1,
            google_spreadsheet_id=None,
            title="Мои расходы",
            reset_day=15,
            timezone="Europe/Moscow",
        )
        text = TableFormatter.link(spreadsheet)

        assert "создаётся" in text
        assert "docs.google.com" not in text


def _draft(*items: DraftItem) -> CheckDraft:
    """Черновик разбора с указанными позициями."""
    return CheckDraft(check_id=1, total=Decimal("100.00"), items=list(items))


class TestCheckFormatter:
    """Списки сопоставления «товар → тип» и «товар → категория»."""

    def test_known_and_suggested_are_split_by_blank_line(self) -> None:
        """Сверху то, что бот знает, снизу то, что предложила модель.

        Разделение существеннее, чем кажется: проверять глазами надо только
        нижний блок, и без него список из полусотни позиций пришлось бы читать
        целиком.
        """
        text = CheckFormatter.types(
            _draft(
                DraftItem(
                    name="молоко",
                    amount=Decimal("89.90"),
                    product_type="молочка",
                    cached_type="молочка",
                ),
                DraftItem(name="конфеты", amount=Decimal("40.00"), product_type="сладости"),
            ),
            {"молочка", "сладости"},
        )

        known, suggested = text.split("\n\n")
        assert known == "1) молоко\n    <b>молочка</b>"
        assert suggested == "2) конфеты\n    <b>сладости</b>"

    def test_new_type_is_shouted(self) -> None:
        """Тип, которого нет ни у одной категории, печатается капсом.

        Единственный способ увидеть до записи, что тип будет заведён.
        """
        text = CheckFormatter.types(
            _draft(DraftItem(name="конфеты", amount=Decimal("40.00"), product_type="сладости")),
            {"молочка"},
        )
        assert "<b>СЛАДОСТИ</b>" in text

    def test_every_line_is_numbered(self) -> None:
        """Номер стоит и у позиции из кэша.

        В старой версии его там не было, и правку типа у уже знакомого товара
        нельзя было даже адресовать — она терялась молча.
        """
        text = CheckFormatter.types(
            _draft(
                DraftItem(
                    name="молоко",
                    amount=Decimal("89.90"),
                    product_type="молочка",
                    cached_type="молочка",
                )
            ),
            {"молочка"},
        )
        assert text.startswith("1) молоко")

    def test_markup_in_product_name_is_escaped(self) -> None:
        """Название из чека не может сломать разметку сообщения.

        Товары приезжают из внешнего источника: «M&S <b>» в названии иначе
        съел бы половину списка или уронил отправку целиком.
        """
        text = CheckFormatter.types(
            _draft(
                DraftItem(name="M&S <b>чай</b>", amount=Decimal("1.00"), product_type="чай")
            ),
            {"чай"},
        )
        assert "M&amp;S &lt;b&gt;чай&lt;/b&gt;" in text
        assert text.count("<b>") == 1

    def test_item_without_value_shows_dash(self) -> None:
        """Позиция без типа не выглядит пустой строкой."""
        text = CheckFormatter.types(
            _draft(DraftItem(name="загадка", amount=Decimal("1.00"))), set()
        )
        assert "<b>—</b>" in text

    def test_categories_split_confirmed_from_suggested(self) -> None:
        """Категория, выведенная типом, стоит выше подсказанной моделью."""
        text = CheckFormatter.categories(
            _draft(
                DraftItem(
                    name="молоко",
                    amount=Decimal("89.90"),
                    category_title="Еда",
                    category_confirmed=True,
                ),
                DraftItem(name="конфеты", amount=Decimal("40.00"), category_title="Еда"),
            )
        )
        known, suggested = text.split("\n\n")
        assert known == "1) молоко\n    <b>Еда</b>"
        assert suggested == "2) конфеты\n    <b>Еда</b>"

    def test_single_block_has_no_trailing_gap(self) -> None:
        """Чек, где все товары знакомы, не печатается с пустым хвостом."""
        text = CheckFormatter.categories(
            _draft(
                DraftItem(
                    name="молоко",
                    amount=Decimal("89.90"),
                    category_title="Еда",
                    category_confirmed=True,
                )
            )
        )
        assert "\n\n" not in text
