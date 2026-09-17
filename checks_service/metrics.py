"""Метрики пайплайна чеков для Prometheus.

Это единственный сервис, у которого есть метрики, и единственный, у которого
они осмысленны: только он видит скан целиком — кто сканировал, какой формат,
сколько шёл внешний сервис расшифровки и чем всё кончилось. В `api` такой
метрики не завести: там нет `telegram_id` (документ, а не пользователь, —
единица владения), а тянуть личность через `CommitCheckRequest` значило бы
ломать слоистость api ради метки, которую Grafana получает join-ом бесплатно.
Сколько позиций записано, дашборд считает прямо по `records`.

**Числа, и только числа.** Содержимое QR-строки, ссылка на чек, названия
товаров сюда не попадают и попасть не могут: у Prometheus каждое сочетание
меток — отдельный временной ряд, и метка со строкой чека означала бы новый ряд
на каждую покупку. Всё это Grafana читает из Postgres напрямую.

**Кардинальность.** Рядов здесь: пользователи × форматы (2) на скан и
пользователи × стадии (2) × причины (~8) на отказы. Ограниченность держится на
трёх вещах, и каждая из них — условие, а не совпадение:

* `reason` — это `ChecksError.code`, закрытое множество из
  :mod:`checks_service.exceptions`;
* `stage` — значение из :data:`checks_service.constants.METRIC_STAGE_BY_PATH`,
  и путь вне карты не считается вовсе;
* `telegram_id` ограничен списком допуска, а неопознанные запросы схлопываются
  в :data:`UNKNOWN_TELEGRAM_ID`.

**Если список допуска когда-нибудь откроют** (`ALLOWED_TELEGRAM_IDS` — сегодня
граница безопасности сервиса), `telegram_id` станет неограниченным, и метку
придётся убрать отсюда, а разбивку по пользователю оставить только
SQL-панелям.

**Реестр глобальный, воркер один.** Счётчики живут в памяти процесса
(`prometheus_client.REGISTRY`), а `uvicorn` здесь запускается с `--workers 1`
(`dockerfiles/checks_service.Dockerfile`). Появится второй воркер — каждый
заведёт свои счётчики, а скрейп будет попадать в случайный, и метрики молча
поделятся, ничего при этом не сломав. Тогда нужен `PROMETHEUS_MULTIPROC_DIR` и
сборщик `prometheus_client.multiprocess`.

Модуль импортирует только `prometheus_client` и :mod:`checks_service.enums`.
`exceptions` он не импортирует намеренно: импорт идёт в обратную сторону —
отказы считаются в обработчике исключений, — и обоюдный импорт замкнул бы цикл.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from checks_service.enums import CheckKind

#: Метка пользователя для запросов, не дошедших до проверки списка допуска.
#: Посторонний не должен уметь заводить новые ряды в хранилище метрик одним
#: лишь обращением к сервису, поэтому все отказы `unauthorized` и `forbidden`
#: складываются в один ряд.
UNKNOWN_TELEGRAM_ID = "unknown"

RECEIPT_PREVIEWS = Counter(
    "receipt_previews",
    "Показанных плашек «распознан чек» (до подтверждения пользователем)",
    ["telegram_id", "kind"],
)

RECEIPT_SAVES = Counter(
    "receipt_saves",
    "Чеков расшифровано и сохранено",
    ["telegram_id", "kind"],
)

RECEIPT_FAILURES = Counter(
    "receipt_failures",
    "Отказов на приёме чека, по стадии и коду отказа",
    ["telegram_id", "stage", "reason"],
)

RECEIPT_FETCH_SECONDS = Histogram(
    "receipt_fetch_seconds",
    "Время похода во внешний сервис расшифровки",
    ["kind", "outcome"],
    # Корзины покрывают оба таймаута: у ФНС 20 с на один запрос, у ПУРС 30 с на
    # каждый из трёх (страница на двух языках и позиции отдельно), то есть до
    # полутора минут в худшем случае.
    buckets=(0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89),
)

_ALL = (RECEIPT_PREVIEWS, RECEIPT_SAVES, RECEIPT_FAILURES, RECEIPT_FETCH_SECONDS)


def observe_preview(telegram_id: int | str, kind: CheckKind) -> None:
    """Плашка показана: формат распознан и документ у пользователя есть."""
    RECEIPT_PREVIEWS.labels(telegram_id=str(telegram_id), kind=kind.value).inc()


def observe_save(telegram_id: int | str, kind: CheckKind) -> None:
    """Чек сохранён целиком."""
    RECEIPT_SAVES.labels(telegram_id=str(telegram_id), kind=kind.value).inc()


def observe_failure(telegram_id: int | str, stage: str, reason: str) -> None:
    """Отказ на приёме чека. `reason` — код исключения, `stage` — этап."""
    RECEIPT_FAILURES.labels(
        telegram_id=str(telegram_id),
        stage=stage,
        reason=reason,
    ).inc()


def observe_fetch(kind: CheckKind, outcome: str, seconds: float) -> None:
    """Поход во внешний сервис расшифровки занял `seconds` и кончился `outcome`."""
    RECEIPT_FETCH_SECONDS.labels(kind=kind.value, outcome=outcome).observe(seconds)


def render() -> tuple[bytes, str]:
    """Текущее состояние метрик и его content-type.

    Существует затем, чтобы `prometheus_client` оставался известен одному
    модулю: роут `/metrics` отдаёт то, что вернули отсюда, и больше ничего о
    формате экспозиции не знает.
    """
    return generate_latest(), CONTENT_TYPE_LATEST


def reset() -> None:
    """Обнуляет все метрики. **Только для тестов.**

    Счётчики — глобальные объекты, созданные на импорте модуля, и переживают
    отдельный тест. Пересоздавать их нельзя: повторная регистрация в том же
    реестре — ошибка `Duplicated timeseries`. `clear()` убирает ряды с метками,
    оставляя сами метрики зарегистрированными.
    """
    for metric in _ALL:
        metric.clear()
