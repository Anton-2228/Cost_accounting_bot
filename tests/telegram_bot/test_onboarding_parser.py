"""Тесты разбора шагов мастера создания таблицы."""

from __future__ import annotations

import pytest

from telegram_bot.parsers import OnboardingParser, ParseError


class TestResetDay:
    """День перехода на новый учётный период."""

    @pytest.mark.parametrize("raw", ["1", "15", "28", " 5 "])
    def test_valid(self, raw: str) -> None:
        """Числа от 1 до 28 принимаются."""
        assert 1 <= OnboardingParser.reset_day(raw) <= 28

    @pytest.mark.parametrize("raw", ["0", "29", "31", "-3"])
    def test_out_of_range(self, raw: str) -> None:
        """29 и больше не принимаются: такого дня нет в феврале.

        Это не придирка к формату, а условие, при котором «то же число
        следующего месяца» всегда существует.
        """
        with pytest.raises(ParseError, match="от 1 до 28"):
            OnboardingParser.reset_day(raw)

    @pytest.mark.parametrize("raw", ["", "первое", "15.5"])
    def test_not_a_number(self, raw: str) -> None:
        """Нечисловой ответ объясняется."""
        with pytest.raises(ParseError, match="не похоже на число"):
            OnboardingParser.reset_day(raw)


class TestTimezone:
    """Часовой пояс документа."""

    @pytest.mark.parametrize("raw", ["Europe/Moscow", "Asia/Yekaterinburg", "UTC"])
    def test_valid(self, raw: str) -> None:
        """Существующие зоны IANA принимаются."""
        assert OnboardingParser.timezone(raw) == raw

    @pytest.mark.parametrize("raw", ["Мск", "Europe/Moskva", "GMT+3:00"])
    def test_unknown(self, raw: str) -> None:
        """Несуществующая зона ловится здесь, а не через месяц на ролловере."""
        with pytest.raises(ParseError, match="не существует"):
            OnboardingParser.timezone(raw)


class TestEmail:
    """Почта для доступа к таблице."""

    @pytest.mark.parametrize(
        "raw",
        [
            "user@gmail.com",
            "first.last@gmail.com",
            "user+tag@gmail.com",
            "user-name@my-domain.ru",
        ],
    )
    def test_valid(self, raw: str) -> None:
        """Обычные живые адреса проходят.

        Старое правило `\\w+@gmail.com` отвергало точку, дефис и плюс в
        локальной части — то есть половину настоящих адресов.
        """
        assert OnboardingParser.email(raw) == raw

    @pytest.mark.parametrize("raw", ["user@gmailXcom", "user@", "@gmail.com", "user", ""])
    def test_invalid(self, raw: str) -> None:
        """Заведомо неверный адрес не проходит.

        `user@gmailXcom` — тот самый случай, который старое правило пропускало:
        точка в нём не была экранирована и совпадала с любым символом.
        """
        with pytest.raises(ParseError):
            OnboardingParser.email(raw)

    @pytest.mark.parametrize("raw", ["-", "нет", "Пропустить"])
    def test_skip(self, raw: str) -> None:
        """Шаг можно пропустить: почта в api необязательна."""
        assert OnboardingParser.email(raw) is None


class TestTitle:
    """Название таблицы."""

    def test_valid(self) -> None:
        """Пробелы по краям срезаются."""
        assert OnboardingParser.title("  Мои расходы  ") == "Мои расходы"

    def test_empty(self) -> None:
        """Пустое название не принимается."""
        with pytest.raises(ParseError, match="пустым"):
            OnboardingParser.title("   ")

    def test_too_long(self) -> None:
        """Слишком длинное название отсекается до запроса."""
        with pytest.raises(ParseError, match="длиннее"):
            OnboardingParser.title("а" * 300)
