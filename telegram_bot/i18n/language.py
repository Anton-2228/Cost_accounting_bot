"""Языки интерфейса бота."""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    """Язык, на котором бот говорит с пользователем.

    Зеркало `api.enums.Language`: значение — то, что лежит в `users.language`.
    Верхний регистр ради правила «имя члена совпадает со значением», которым
    живут все перечисления проекта. Наружу — в имена каталогов, в Babel и в
    `callback_data` — язык выходит кодом в нижнем регистре (:attr:`code`).
    """

    RU = "RU"
    EN = "EN"
    HI = "HI"
    ES = "ES"
    FR = "FR"

    @property
    def code(self) -> str:
        """Код языка ISO 639-1: `ru`, `en`, …"""
        return self.value.lower()

    @classmethod
    def from_code(cls, code: str) -> Language | None:
        """Язык по коду в любом регистре или `None`, если такого нет."""
        try:
            return cls(code.strip().upper())
        except ValueError:
            return None


#: Порядок кнопок выбора языка. Английский первым: выбор на `/start`
#: показывается ещё до того, как бот знает язык человека, и подпись над
#: кнопками английская.
PICKER_ORDER: tuple[Language, ...] = (
    Language.EN,
    Language.RU,
    Language.HI,
    Language.ES,
    Language.FR,
)

#: Надписи кнопок: флаг и самоназвание. Не переводятся — человек ищет свой язык
#: по тому, как он называется на нём самом.
NATIVE_LABELS: dict[Language, str] = {
    Language.EN: "🇬🇧 English",
    Language.RU: "🇷🇺 Русский",
    Language.HI: "🇮🇳 हिन्दी",
    Language.ES: "🇪🇸 Español",
    Language.FR: "🇫🇷 Français",
}

#: Названия языков по-английски — для промптов модели.
ENGLISH_NAMES: dict[Language, str] = {
    Language.EN: "English",
    Language.RU: "Russian",
    Language.HI: "Hindi",
    Language.ES: "Spanish",
    Language.FR: "French",
}

#: Язык тех, кто его ещё не выбирал. Повторяет умолчание колонки
#: `users.language` в api: бот, не нашедший пользователя, обязан говорить с ним
#: на том же языке, который api запишет при первой встрече.
#:
#: Читается через модуль, а не импортом имени: тесты бота подменяют его на
#: русский, и копия, снятая на импорте, подмены бы не увидела.
DEFAULT_LANGUAGE = Language.EN
