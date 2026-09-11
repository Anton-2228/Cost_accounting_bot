"""Уведомления пользователю: код и данные для подстановки.

Текста здесь нет. Весь текст пользователю живёт в боте, в каталогах пяти языков,
и собирается там по коду: api решает, *о чём* сообщить, а бот — *как* это
сказать на языке человека. Прежде здесь лежали готовые русские фразы, и
англоязычный пользователь получал бы уведомления по-русски.

Сообщение рождается в фоновой работе, у которой нет HTTP-ответа, и собирается
из данных документа, поэтому и едет не кодом ошибки в ответе, а строкой очереди
`user_notifications`. Каждому коду отсюда в каталоге бота соответствует
шаблон `notification.<код>` с теми же подстановками.
"""

from __future__ import annotations

from datetime import date

from api.domain.user_message import UserMessage

#: Название листа, который читается обратно в базу. Оно попадает в сообщение,
#: поэтому лежит здесь: раскладку документа api не знает и знать не должен, а
#: вот назвать пользователю вкладку, о которой идёт речь, обязан. Названия
#: листов не переводятся — лист зовётся так в любой таблице.
CATEGORIES_SHEET_TITLE = "Categories"


def table_ready(google_spreadsheet_id: str) -> UserMessage:
    """Google-документ создан и готов к работе.

    Едет идентификатор, а не ссылка: адрес бот собирает сам тем же шаблоном,
    каким отвечает на кнопку «Получить таблицу», и второй его копии здесь не
    нужно.
    """
    return UserMessage(
        code="table_ready",
        params={"google_spreadsheet_id": google_spreadsheet_id},
    )


def import_ok(sheet_title: str) -> UserMessage:
    """Лист прочитан, правки применены.

    Сообщение уходит и тогда, когда импорт ничего не изменил. Пользователь
    правил лист и ждёт ответа; молчание при «ноль создано, ноль обновлено» он
    прочитает как «меня не услышали» — ровно та неопределённость, ради которой
    уведомление и заводится.
    """
    return UserMessage(code="import_ok", params={"sheet": sheet_title})


def rollover_done(start_date: date) -> UserMessage:
    """Начался новый расчётный период."""
    return UserMessage(code="rollover_done", params={"start_date": start_date.isoformat()})


def sync_failed(attempts: int) -> UserMessage:
    """Перерисовка листа не удаётся раз за разом."""
    return UserMessage(code="sync_failed", params={"attempts": attempts})


def sync_terminal(error: str) -> UserMessage:
    """Перерисовка невозможна, пока пользователь не вмешается.

    Текст ошибки едет целиком: он приходит от Google и объясняет причину
    точнее, чем любая наша формулировка. Само сообщение — не «всё пропало»:
    задача осталась в очереди и выполнится, как только препятствие исчезнет.
    """
    return UserMessage(code="sync_terminal", params={"error": error})


def access_failed(email: str) -> UserMessage:
    """Google отказался выдать доступ на эту почту."""
    return UserMessage(code="access_failed", params={"email": email})
