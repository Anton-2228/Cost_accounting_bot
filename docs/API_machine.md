# `api/` — карта модуля и план работ

Документ для последующих сессий. Описывает **что уже сделано** в `new_version/api`,
какие инварианты нельзя нарушать и **что делать дальше**.

Пиши на русском: сообщения пользователю, комментарии, докстринги, сообщения
коммитов.

---

## 1. Контекст

Переписывание с нуля старого проекта `/root/Cost_accounting_bot` (учёт личных
расходов). Архитектурный эталон — `/root/sales_analysis`, его конвенции
воспроизводятся точно.

Система из четырёх частей:

| Часть | Состояние | Ответственность |
|---|---|---|
| `api/` | **готов** | Владеет Postgres. Вся предметная логика и все деньги |
| `google_sheets_service/` | **готов**, см. [GSHEETS_machine.md](GSHEETS_machine.md) | Единственный, кто ходит в Google API. Разгребает очередь перерисовки, читает правки пользователя и отдаёт в api |
| `telegram_bot/` | **готов**, см. [BOT_machine.md](BOT_machine.md) | aiogram-фронтенд: разбирает ввод, зовёт api, печатает ответ по-русски |
| `checks_service/` + `mini_app/` | **готов**, см. [CHECKS_machine.md](CHECKS_machine.md) | Единственная публичная часть системы: Mini App сканирует QR-код чека, сервис получает расшифровку и кладёт сырьё в api |

Разбор чека — последняя недостающая часть — сделан и живёт в боте
([BOT_machine.md](BOT_machine.md) §10). Незакрытых пунктов плана больше нет.

**Api никогда не ходит в Google.** Мутация — одна короткая транзакция в Postgres,
которая заодно пишет строку в очередь `sheet_sync_tasks`. Отсюда главное
свойство: операция не может ответить пользователю ошибкой после того, как деньги
уже списаны.

---

## 2. Что сделано

Каркас, слой данных, сервисный слой, HTTP-слой и фоновый ролловер. Проверено, а
не заявлено:

| Проверка | Команда | Результат |
|---|---|---|
| Линтер | `uv run ruff check .` | чисто |
| Типы | `uv run mypy api checks_service google_sheets_service telegram_bot tests` | чисто, 397 файлов |
| Тесты | `uv run pytest` | 586 тестов (вместе с gsheets, ботом и чеками) |
| Обратимость миграции | `alembic upgrade head` → `downgrade base` → `upgrade head` | типы и таблицы вычищаются полностью |
| Миграция == `create_all` | `pg_dump` обеих схем + diff | идентичны |
| Запуск с нуля | `docker compose up -d --build` | миграция применяется, `/health/ready` отвечает, healthcheck зелёный |

Тестам нужен настоящий Postgres 16 (нативные enum, `IDENTITY`, частичные и
выражательные индексы, `UNIQUE NULLS NOT DISTINCT`, отложенные составные ключи):

```bash
docker run -d --name pg-test -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \
    -e POSTGRES_DB=cost_test -p 5544:5432 postgres:16
uv run pytest
```

### Дерево

```
new_version/
├── pyproject.toml · uv.lock · alembic.ini · docker-compose.yml · README.md
├── deploy/nginx/                # публикация Mini App: сайт + сниппет для nginx хоста
├── dockerfiles/{api,google_sheets_service,telegram_bot,checks_service}.Dockerfile
├── scripts/entrypoint.sh        # ждёт Postgres → alembic upgrade head → uvicorn
├── env/{api,postgres,google_sheets_service,telegram_bot,checks_service}.env.example
├── docs/API_machine.md          # этот файл
├── docs/GSHEETS_machine.md      # карта google_sheets_service
├── docs/BOT_machine.md          # карта telegram_bot
├── docs/CHECKS_machine.md       # карта checks_service и mini_app
├── google_sheets_service/       # разбор очереди и работа с Google
├── telegram_bot/                # aiogram-фронтенд
├── checks_service/              # бэкенд Mini App: QR → расшифровка → чек в api
├── mini_app/                    # статика Mini App, без сборщика
├── api/
│   ├── main.py                  # create_app() + app, lifespan (в нём же ролловер)
│   ├── core/                    # config, constants, logging, messages, period, text, types
│   ├── db/                      # base, mixins, engine, session, transaction, column_types
│   ├── enums/                   # 7 файлов, по одному на enum
│   ├── orm/                     # 16 таблиц + __init__ (регистрация в Base.metadata)
│   ├── domain/                  # pydantic-зеркало + производные модели
│   ├── mappers/                 # base + 12
│   ├── repositories/            # base + 13
│   ├── services/                # base, _periods + 11 сервисов
│   ├── tasks/                   # rollover_loop.py
│   ├── validation.py            # разбор листов, русские тексты ошибок
│   ├── exceptions/              # base, handlers
│   ├── requests/                # подпакет на домен, extra="forbid"
│   ├── responses/               # common (DataResponse, ItemsResponse, Page, Error) + по домену
│   ├── dependencies/            # repositories.py, services.py
│   ├── routers/                 # system + 9 доменных, 34 маршрута
│   └── alembic/versions/  # c05740c0de01 (схема) + 7f3c1d9a4b02 (аренда задачи)
│                           # + b1e6a4c7d905 (чеки) + d4c7b2e910a3 (разбор чека)
│                           # + e5a1f83b2c47 (лист чеков, подтверждение импорта)
└── tests/
    ├── conftest.py · factories.py
    ├── unit/         # period, text, mappers, rollover_loop
    ├── repositories/ # по файлу на репозиторий + test_source_balance.py
    ├── services/     # conftest с фикстурами сервисов + по файлу на сервис
    ├── db/test_schema_constraints.py
    ├── api/          # по файлу на роутер
    ├── google_sheets_service/  # фейки Google, unit и тесты движка
    ├── telegram_bot/
    └── checks_service/         # парсер ФНС, реестр, initData, роутеры Mini App
```

**Разбор чека** сырьё не трогает: api по-прежнему не интерпретирует
`raw_payload` ни одним полем. Из него позиции достаёт бот, а сюда приезжает
готовый результат — см. [CHECKS_machine.md](CHECKS_machine.md) §8 и
[BOT_machine.md](BOT_machine.md) §10.

---

## 3. Конвенции (соблюдать)

- **Один класс — один файл**, имя файла snake_case по сущности. ORM с суффиксом
  `ORM` (`CategoryORM`), доменные — голым существительным (`Category`).
- `from __future__ import annotations` после однострочного докстринга модуля.
  Русские докстринги на модуль, класс и каждый публичный метод.
- PEP 695 generics: `class BaseRepository[ORM_T: Base, DOMAIN_T]`, `class Page[T]`.
  Никогда `Generic[T]`.
- Всё async. Сессия — per-request `Depends(get_session)`.
- Слои: `router → service → repository → mapper → ORM`. Инварианты:
  - ORM-объект **не покидает репозиторий**;
  - HTTP-схема **не доходит до репозитория** (роутер превращает её в доменную
    модель или в аргументы метода сервиса);
  - конвертация только в маппере, `to_orm` не ставит `id`/`created_at`/`updated_at`;
  - domain → response конвертируется **в роутере** через `Response.model_validate(...)`.
- **Репозитории только `flush`/`refresh`, никогда не коммитят.** Коммитит сервис
  ровно одним вызовом `api.db.transaction.commit(session)`.
- Приватные атрибуты `self._x`, всё после первого позиционного — keyword-only.
- Логирование %-стилем, не f-строками: `logger.info("Создан документ %s", id)`.
- Строка длиной до 100 символов.

---

## 4. Схема БД

16 таблиц. Enum нативные, `StrEnum`, **имя члена == значение** (SQLAlchemy пишет
в БД имя).

| Enum | Значения |
|---|---|
| `entity_status` | `ACTIVE`, `INACTIVE` — намеренно **без** `DELETED` |
| `category_kind` | `INCOME`, `EXPENSE` |
| `check_kind` | `RU_FNS` — формат чека; зеркалится в `checks_service/enums.py` |
| `period_status` | `OPEN`, `CLOSED` |
| `sheet_target` | `STRUCTURE`, `CATEGORIES`, `BILLS`, `OPERATIONS`, `STATISTICS`, `CHECKS` |
| `sync_task_kind` | `REDRAW` (БД → лист), `IMPORT` (лист → БД) |
| `access_role` | `READER`, `WRITER` |
| `notification_kind` | `TABLE_READY`, `IMPORT_OK`, `IMPORT_ERROR`, `SYNC_FAILED`, `ROLLOVER` |

Миксины: `PkMixin` (BIGINT IDENTITY), `TimestampMixin`, `SoftDeleteMixin`
(`deleted_at`). Деньги везде `NUMERIC(14,2)` / `Decimal`.

| Таблица | Ключевое |
|---|---|
| `users` | `telegram_id` UNIQUE |
| `spreadsheets` | `user_id` FK UNIQUE (один пользователь — одна таблица); `google_spreadsheet_id` **nullable** UNIQUE; `reset_day` SMALLINT CHECK 1..28; `timezone` VARCHAR default `Europe/Moscow` |
| `spreadsheet_accesses` | `(spreadsheet_id, email)` UNIQUE, `granted_at` NULL = «выдать предстоит» |
| `periods` | UNIQUE `(spreadsheet_id, start_date)`; UNIQUE `(id, spreadsheet_id)`; CHECK `end_date > start_date` |
| `categories` | `kind`, `status`, `title`; партиальный UNIQUE `(spreadsheet_id, lower(title)) WHERE deleted_at IS NULL` |
| `category_associations` | `(spreadsheet_id, alias)` UNIQUE; CHECK `alias = lower(alias)` |
| `category_product_types` | `(spreadsheet_id, product_type)` UNIQUE; CHECK lower |
| `sources` | `start_balance NUMERIC(14,2)`. **`current_balance` отсутствует** |
| `source_associations` | `(spreadsheet_id, alias)` UNIQUE (своё пространство имён) |
| `records` | `amount` **знаковая и может быть нулевой**, `added_at DATE`, `period_id`/`category_id`/`source_id`/`check_id` — составные FK, `deleted_at`, `product_name`/`product_type` |
| `transfers` | `from_source_id`/`to_source_id`, `amount` CHECK `> 0`, CHECK `from <> to` |
| `cashed_records` | UNIQUE `(spreadsheet_id, product_name)` |
| `checks` | сырьё чека: `kind`, `qr_raw`, `external_key`, `raw_payload` JSONB, `fetched_at`, `processed_at`; UNIQUE `(spreadsheet_id, kind, external_key)`; UNIQUE `(id, spreadsheet_id)`; партиальный индекс очереди `WHERE processed_at IS NULL` |
| `sheet_sync_tasks` | очередь, см. §5 |
| `sheet_mappings` | `(spreadsheet_id, target, period_id) → google_sheet_id, title` |
| `user_notifications` | исходящие сообщения, `delivered_at`; партиальный индекс по недоставленным |

**Составные внешние ключи** везде, где есть `spreadsheet_id`:
`records.(category_id, spreadsheet_id) → categories.(id, spreadsheet_id)` и т. д.
Поэтому «операция ссылается на категорию из чужого документа» — невыразимое
состояние, а не то, что должен не забыть проверить сервис.

Ключи на `periods`/`categories`/`sources` объявлены `DEFERRABLE INITIALLY
DEFERRED`: при удалении документа Postgres каскадно удаляет и операции, и
справочники, а порядок между каскадами не определён. Отложенная проверка
выполняется один раз в конце транзакции, когда удалено уже всё. **Не менять на
немедленные** — удаление документа начнёт падать.

---

## 5. Очередь перерисовки листов (`sheet_sync_tasks`)

Центральный механизм. Инвариант: **строка описывает не изменение, а
устаревание.** Она не несёт данных о том, что произошло, — только адрес листа.
Перерисовка всегда строится из текущего состояния БД целиком, поэтому повтор
безопасен, порядок обработки не важен, а единственный возможный сбой — потеря
задачи, которая чинится следующей же правкой или ручной синхронизацией.

```sql
CONSTRAINT uq_sheet_sync_tasks_key
    UNIQUE NULLS NOT DISTINCT (spreadsheet_id, kind, target, period_id)
CONSTRAINT ck_sheet_sync_tasks_period_matches_target
    CHECK ((target IN ('OPERATIONS','STATISTICS','CHECKS')) = (period_id IS NOT NULL))
CONSTRAINT ck_sheet_sync_tasks_import_target
    CHECK (kind <> 'IMPORT' OR target IN ('CATEGORIES','BILLS'))
```

- `NULLS NOT DISTINCT` требует **PostgreSQL 15+**. У `CATEGORIES`/`BILLS`/
  `STRUCTURE` период пуст; без этого схлопывание для них не работало бы и задачи
  копились бы без предела.
- CHECK по периоду **двусторонний**. Односторонняя формулировка пропустила бы
  задачу `CATEGORIES` с периодом: она не совпала бы по ключу с нормальной, не
  схлопнулась бы и висела вечно.
- `kind` входит в ключ: перерисовка и импорт одного листа — разные работы, и
  схлопнись они в одну строку, одна из двух потерялась бы совсем.

Методы `SheetSyncTaskRepository`:

| Метод | Назначение |
|---|---|
| `enqueue(spreadsheet_id, target, period_id=None, *, kind=REDRAW)` | `ON CONFLICT DO UPDATE`: двигает `requested_at`, не создаёт дубль |
| `enqueue_many(keys)` | один оператор; **дедуплицирует ключи в Python** — PG падает на двух одинаковых ключах в одном INSERT |
| `claim(limit)` | `FOR UPDATE SKIP LOCKED`; **вызывающий обязан сразу закоммитить** — блокировки живут до конца транзакции |
| `complete(task_id, requested_at)` | условное удаление; `False` = пришла новая правка |
| `release(task_id)` | снять захват после `complete() is False` |
| `fail(task_id, error)` | `attempts + 1`, экспоненциальная пауза, текст в `last_error`; возвращает обновлённую задачу |

В `enqueue` `LEAST(...)` ссылается **на колонку таблицы**, не на `excluded`: в
`excluded` лежит серверный `now()` вставляемой строки, `LEAST` выродился бы и
backoff перестал бы работать.

---

## 6. Инварианты, которые нельзя нарушать

1. **Баланс не хранится.** Считается `SourceRepository.balances()` тремя
   **коррелированными подзапросами**. Три `LEFT JOIN` с `GROUP BY` дадут
   декартово произведение — тест `test_balance_with_records_and_transfers_on_both_sides`
   специально построен так, чтобы это поймать.
2. **Деньги — `Decimal`.** Ни одного `float`, ни одного `int()`/`round()` по пути
   от БД к листу.
3. **Знак — свойство категории.** `records.amount` знаковая
   (`SignedMoneyDecimal`), `transfers.amount` строго положительная
   (`PositiveMoneyDecimal`). Наружу суммы принимаются **без знака**. Общий
   `MoneyDecimal` на `Record.amount` завалит валидацией каждый расход.
4. **Периоды полуинтервальные `[start, end)`.** Отбор операций — по `period_id`,
   не по диапазону дат.
5. **`added_at` вычисляет код** по `spreadsheets.timezone`, не `server_default`.
   Для `Europe/Moscow` сутки сменяются в 21:00 UTC.
6. **`reset_day` строго 1..28.** Только это делает `replace(day=...)` и сдвиг на
   месяц всегда валидными.
7. **Псевдонимы нормализованы** валидатором доменной модели (`normalize_terms`).
   `CHECK` в БД не пропустит ненормализованное значение никаким путём.
8. **Удаление мягкое** (`deleted_at`), и `soft_delete` идемпотентен за счёт
   условия `deleted_at IS NULL`. Единственное исключение — удаление документа:
   оно физическое, каскадом от `users`.
9. **Схема меняется только миграцией.** `create_all` живёт исключительно в
   тестах. Партиальные, GIN- и выражательные индексы Alembic autogenerate **не
   видит** — писать руками и дублировать в `__table_args__`, иначе тесты будут
   зелёными на схеме, которой нет в проде.
10. **Период закрывается ролловером, как только закончился.** Закрытый период не
    меняется и выпадает из веера задач. Без этого `list_open` через два года
    заставлял бы одну правку справочника перерисовывать все месяцы за всю
    историю документа.
11. **Чтение ничего не создаёт.** Период создают только операция (лениво, под
    сегодняшнюю дату) и ролловер; `GET /periods/current` на его отсутствие
    отвечает 404.

---

## 7. Решения, принятые при доводке api

| Решение | Выбор и почему |
|---|---|
| Распределённые транзакции (`X-Transaction-Id` из эталона) | **не портированы**: здесь нет клиента, которому нужен атомарный этап из нескольких запросов. Чек и так приезжает одним вызовом. Добавить позже — механическая замена `commit` на `maybe_commit` |
| Схемы ответов | отдельные `api/responses/<домен>/*_response.py`; внутренние поля (`deleted_at`, `spreadsheet_id`) не выдаются |
| Служебные эндпоинты для gsheets | **одна плоская поверхность** с пользовательскими, различие — тег `service` в Swagger. Аутентификации нет: api не публикуется наружу |
| Закрытие периода | сразу на ролловере. Цена: удаление операции прошлого месяца — 422. Ввод задним числом невозможен в принципе, поэтому больше эта плата ничего не стоит |
| Ролловер | asyncio-задача в `lifespan` + `pg_try_advisory_xact_lock(namespace, spreadsheet_id)` на каждый документ. Транзакционная блокировка снимается сама, поэтому «api строго в один воркер» больше не требуется |
| Перевод на листе | одна строка в реестре операций (`Category = «Перевод»`, `Source = «А → Б»`). Отдельный `SheetTarget` не вводился |
| `records.check_json` | **удалён** (`d4c7b2e910a3`): с появлением `records.check_id` копия JSON в каждой позиции стала дублем строки `checks`. `RecordResponse` отдаёт наружу сам `check_id` (`e5a1f83b2c47`): в колонке `Check` реестра печатается номер чека, а расшифровка лежит строкой на листе-архиве |
| Категории и счета | правятся **только** через лист + импорт. Один путь записи — нечему расходиться |
| Списки | `ItemsResponse[T]` (одно поле `items`). `Page[T]` остаётся для выборок, способных вырасти; сейчас таких нет |

---

## 8. Поверхность API

Префикс `/api/v1`, вне него — только `/health` и `/health/ready`.

| Метод и путь | Назначение |
|---|---|
| `POST /spreadsheets` | создать таблицу (`/start`), 201; повтор — 409 |
| `GET /spreadsheets/by-telegram/{telegram_id}` | таблица пользователя (объявлен **до** `/{id}`) |
| `GET /spreadsheets/{id}` · `DELETE /spreadsheets/{id}` | чтение, удаление (204) |
| `GET /spreadsheets/{id}/categories` · `sources` · `balances` | справочники, `?only_active=` |
| `GET/POST /spreadsheets/{id}/accesses` · `POST .../accesses/{id}/granted` | доступы; `?pending_only=` |
| `POST /spreadsheets/{id}/sync` | попросить вчитать листы, 202 |
| `POST /spreadsheets/{id}/google-id` | привязать созданный документ (для gsheets) |
| `GET/POST /spreadsheets/{id}/records` · `DELETE .../records/last` · `.../records/{id}` | операции; `?period_id=` |
| `GET/POST /spreadsheets/{id}/transfers` · `DELETE .../transfers/last` · `.../transfers/{id}` | переводы |
| `GET /spreadsheets/{id}/periods` · `.../periods/current` · `.../periods/{id}/statistics` | периоды и дневные итоги |
| `GET/POST /spreadsheets/{id}/checks` | сохранённые чеки, `?unprocessed=` (очередь разбора) либо `?period_id=` (архив месяца для листа чеков); оба фильтра сразу — 422; повтор — 409 `check_already_saved` |
| `DELETE /spreadsheets/{id}/checks/{check_id}` | убрать неразобранный чек (204); разобранный — 409 `check_already_processed` |
| `GET /spreadsheets/{id}/cashed-records` · `POST .../checks/commit` | кэш типов, запись разобранного чека |
| `GET /spreadsheets/{id}/notifications` · `POST .../notifications/{id}/delivered` | сообщения боту |
| `POST /spreadsheets/{id}/import/categories` · `.../import/bills` | лист → БД (для gsheets) |
| `GET/POST /spreadsheets/{id}/sheet-mappings` | где лежит лист (для gsheets) |
| `POST /sheet-sync-tasks/claim` · `.../{id}/complete` · `.../{id}/fail` | очередь (для gsheets) |

`?period_id=` необязателен: без него берётся текущий период. Один эндпоинт
обслуживает и бота («покажи мои операции»), и gsheets («перерисуй лист периода 7»).

Конверты: `{"data": ...}` для одиночного ресурса, `{"items": [...]}` для списка,
`{"code", "message", "details"}` для ошибки. **Русский текст для пользователя
живёт в боте** и подбирается по `code`. Исключения — два, и оба потому, что текст
собирается из пользовательских данных: разбор листа (`api/validation.py`, едет в
поле `error` ответа импорта) и уведомления фоновой работы (`api/core/messages.py`).

---

## 9. Что делать дальше

### Шаг 1. `google_sheets_service/` — сделан

Раскладка листов, механика перерисовки и разбор очереди описаны в
[GSHEETS_machine.md](GSHEETS_machine.md). Ради него в api появились три вещи
(миграция `7f3c1d9a4b02`):

- **срок аренды забранной задачи** — `claim` отбирает и просроченные захваты,
  иначе умерший воркер замораживал лист навсегда и молча;
- **признак `terminal` в `fail`** — 403 и 404 от Google повтором не лечатся, и
  ждать пятой попытки значит молчать полчаса о том, что известно с первой;
- **`POST /spreadsheets/{id}/accesses/{id}/failed`** — почта, которую Google не
  принял, удаляется, иначе попадала бы в каждую последующую сверку скелета.

### Шаг 2. `telegram_bot/` — сделан

Aiogram-3 фронтенд, описан в [BOT_machine.md](BOT_machine.md). В боте осталось
только представление: подбор по псевдонимам, состояние FSM, русские тексты. Вся
арифметика и все деньги — в api.

Ради него в api появилась **доставка уведомлений push-ом** (миграции не
потребовалось):

- `UserNotificationRepository.list_undelivered_all()` — вся очередь одним
  запросом с join'ом до `users.telegram_id`. Уведомление знает только документ,
  а отправлять надо в чат; без `telegram_id` бот не смог бы узнать, у кого
  спрашивать, не заведя собственный список пользователей — второй источник
  истины о том, кто вообще есть;
- доменная модель `PendingNotification` — результат выборки с join'ом, обратного
  отображения в ORM у неё нет;
- `api/tasks/notification_loop.py` — цикл в `lifespan` рядом с ролловером: берёт
  недоставленные, толкает боту, по 2xx ставит `delivered_at`. Он же и есть
  механизм повтора: бот, лежавший в момент правки листа, получит текст разбора
  следующим проходом. **Пустой `BOT_NOTIFY_URL` выключает рассылку** — api
  обязан подниматься и без бота.

`GET /spreadsheets/{id}/notifications` и `POST .../delivered` сохранены: по ним
бот дочитывает пропущенное при обращении пользователя, а подтверждение общее для
обоих путей — одно сообщение не уходит дважды.

### Шаг 3. Вход чеков — сделан

`checks_service` и `mini_app`, описаны в [CHECKS_machine.md](CHECKS_machine.md).
Ради них в api появилось (миграция `b1e6a4c7d905`):

- таблица **`checks`** и enum `check_kind` — сырьё чека и его формат. Ни даты,
  ни суммы, ни валюты отдельными колонками: форматов будет больше одного, и
  выбрать, чью сумму считать настоящей, можно только на разборе;
- **`check_queue_items` удалена целиком** вместе с репозиторием, доменной
  моделью, маппером, тремя эндпоинтами очереди и параметром `check_id` у
  `POST /checks/commit`. Наполнять её было нечем: старый Telethon-слушатель
  отключён, а `POST /checks-queue` никто не звал;
- `POST /spreadsheets/{id}/checks` с дублем, пойманным дважды — предварительной
  проверкой ради внятной причины и `IntegrityError` ради гонки двух
  одновременных сканов.

**Инварианты целы:** api по-прежнему не делает ни одного внешнего вызова и
по-прежнему не публикуется наружу. Наружу смотрит один поддомен, за которым
стоит один `checks_service`, — он же единственный, кто ходит во внешний мир.

### Шаг 4. Разбор чека — сделан

`checks` → типы товаров → категории → операции реестра. Диалог живёт в боте
([BOT_machine.md](BOT_machine.md) §10), карта разбора сырья — в
[CHECKS_machine.md](CHECKS_machine.md) §8. Ради него в api появилось (миграция
`d4c7b2e910a3`):

- **`checks.processed_at`** — единственный признак разбора. Отдельного статуса
  нет: разбор либо записал операции и проставил метку одной транзакцией, либо не
  сделал ни того, ни другого. Плюс партиальный индекс
  `(spreadsheet_id, id) WHERE processed_at IS NULL` — очередь бота — и
  `UNIQUE (id, spreadsheet_id)` как цель составного FK, ровно как у `periods`;
- **`records.check_id`** вместо `records.check_json`. Ключ составной и
  отложенный: при удалении документа порядок каскадов не определён. `ondelete`
  не ставится — удалять разрешено только неразобранный чек, у которого операций
  нет по определению;
- **`CHECK amount <> 0` снят с `records`.** Позиция чека с нулевой ценой законна
  («второй товар в подарок»), и отбросить её нельзя: сумма записанных позиций
  перестала бы сходиться с итогом чека, которым разбор себя проверяет.
  `CreateRecordRequest.amount` остаётся `gt=0` — строгость держится на пути
  записи обычной операции, а не в таблице;
- **`commit_check` принимает `check_id`**: проверяет принадлежность документу и
  `processed_at IS NULL`, проставляет `records.check_id` и `checks.processed_at`
  **в той же транзакции**, что и операции. Инвариант «ни одна часть не уцелеет
  без остальных» распространяется и на отметку;
- **два новых 409**: `check_already_processed` и `product_type_taken`. Второй
  ловится дважды — предварительной проверкой ради названия чужой категории и
  `IntegrityError` ради гонки с импортом справочника из листа;
- `?unprocessed=` у списка чеков и `DELETE /spreadsheets/{id}/checks/{check_id}`.

**Инварианты целы:** api по-прежнему не интерпретирует `raw_payload` ни одним
полем и не делает ни одного внешнего вызова. Ключ модели живёт у бота.

### Шаг 5. Архив чеков в таблице и подтверждение импорта — сделан

Миграция `e5a1f83b2c47`. Таблица используется в том числе как архив, и отметка
«чек был» архивом не является: теперь расшифровка чека лежит в самой таблице
строкой на отдельном листе, а в колонке `Check` реестра стоит его номер.

- **`sheet_target.CHECKS`** — лист-архив разобранных чеков месяца. Адресат
  периодный, поэтому двусторонний CHECK в `sheet_sync_tasks` и `sheet_mappings`
  пополнился третьим значением. `ck_sheet_sync_tasks_import_target` не тронут:
  он уже делает «импорт архива чеков» невыразимым;
- **`GET /spreadsheets/{id}/checks?period_id=`** — архив месяца. Своего периода
  у чека нет: он приезжает из Mini App задолго до разбора, а месяц ему
  назначают операции. Выборка выводит принадлежность из `records.check_id`
  **без** фильтра `deleted_at IS NULL`: пользователь, удаливший строку реестра,
  не отзывал чек, и зависимость от мягкого удаления молча выносила бы чек из
  архива. Вместе с `?unprocessed=` фильтр несовместим — 422, а не пустой список;
- **`RecordResponse.check_id`** вместо вычисляемого `from_check`. Свернуть
  номер в галочку больше не во что: он и есть ссылка на строку архива;
- **`SpreadsheetResponse.created_at`** выдаётся наружу не ради показа: вместе с
  `id` он образует метку, которой `google_sheets_service` помечает документ в
  Drive и по которой находит его при повторе создания. Одного `id` мало — он
  уникален лишь в пределах одной жизни базы, и пересозданная база подхватывала
  по метке чужой документ от прежних запусков вместо создания нового. Схему это
  не меняет: `created_at` уже есть у `TimestampMixin`;
- **`notification_kind.IMPORT_OK`** — подтверждение прочитанного листа, по
  одному на `Categories` и `Bills`. До сих пор импорт сообщал о себе только
  ошибкой, и пользователь, поправивший опечатку, не имел способа убедиться, что
  правку увидели. Уведомление пишется **в той же транзакции**, что и правки:
  иначе возможно «сообщили об успехе, а импорт откатился». Счётчиков в тексте
  нет намеренно — подтверждение не зависит от того, изменилось ли что-нибудь.

**Грабли миграции.** `ALTER TYPE ... ADD VALUE` выполняется в
`autocommit_block`: использовать новое значение enum в той же транзакции, где
оно добавлено, PostgreSQL запрещает, а следующим шагом идёт CHECK с литералом
`'CHECKS'`. `IMPORT_OK` добавляется с явным `BEFORE 'IMPORT_ERROR'` — иначе
метка встала бы в конец типа и схема разошлась бы с `create_all`. В `downgrade`
тип пересоздаётся целиком (`DROP VALUE` в PostgreSQL не существует), и перед
этим снимаются **все** CHECK по колонке `target`, включая `import_target`:
после переименования типа литералы в уцелевшем условии остаются старого типа, и
`ALTER COLUMN ... TYPE` падает с «operator does not exist: sheet_target =
sheet_target_old».

---

## 10. Как добавить новый домен

1. `api/enums/<name>.py` при необходимости.
2. `api/orm/<entity>.py` + строка в `api/orm/__init__.py`.
3. `api/domain/<entity>.py`.
4. `api/mappers/<entity>_mapper.py` + строка в `__init__`.
5. `api/repositories/<entity>_repository.py` + строка в `__init__`.
6. `api/services/<entity>_service.py`.
7. `api/requests/<домен>/` и `api/responses/<домен>/`.
8. Фабрики в `api/dependencies/repositories.py` и `services.py`.
9. `api/routers/<домен>.py` + `api_router.include_router(...)`.
10. Миграция: `uv run alembic revision --autogenerate -m "..."`, затем **прочитать
    глазами** — партиальные, GIN- и выражательные индексы автогенерация не видит.
11. Тесты: репозиторий, ограничения схемы, сервис, эндпоинт.

---

## 11. Грабли

1. **Автогенерация Alembic и enum.** Вставляет `sa.Enum(..., metadata=MetaData())`
   — не импортируется и не работает. Правило: типы объявлять модульными
   `postgresql.ENUM(..., create_type=False)`, создавать явно в начале `upgrade()`,
   удалять в конце `downgrade()` **после** таблиц (пока на тип ссылается колонка,
   `DROP TYPE` не проходит). Готовый образец — `c05740c0de01_initial_schema.py`.
2. **Переприсваивание дочерней коллекции не работает.** SQLAlchemy в одном
   `flush` выдаёт `INSERT` раньше `DELETE`, и `delete-orphan` не спасает:
   добавление одного псевдонима к набору падает на уникальном ключе. Всегда
   `DELETE` → `flush` → `INSERT`, и **сразу по всему документу**
   (`replace_associations_bulk`): обмен псевдонимами между двумя категориями
   по одной категории неисполним.
3. **`FOR UPDATE` несовместим с `GROUP BY`/`DISTINCT`/агрегатами.** Подзапрос
   отбора в `claim` должен остаться простым `SELECT id`.
4. **`ON CONFLICT DO UPDATE` и дубли в одном операторе** → `command cannot affect
   row a second time`. Дедуплицировать ключи заранее.
5. **`expire_on_commit=False` обязателен.** Иначе доступ к атрибуту после
   `commit()` уходит в БД внутри синхронного кода и падает с `MissingGreenlet`.
   Обратная сторона: после `UPDATE` объект в сессии остаётся прежним, поэтому
   изменённую запись надо возвращать через `RETURNING`, а не перечитывать
   (`SpreadsheetRepository.set_google_spreadsheet_id`).
6. **`lazy="selectin"` — единственный безопасный вариант** подгрузки связей в
   async. Обычная ленивая загрузка сработает при обращении к атрибуту, где негде
   поставить `await`.
7. **`NullPool` в тестах.** Без него соединения asyncpg переживают тест и
   привязываются к другому циклу событий.
8. **`ZoneInfo` требует пакет `tzdata`** в slim-образе; он в зависимостях, не
   удалять. Часовой пояс документа приходит от пользователя, поэтому неизвестное
   значение — рабочий случай: ролловер ловит ошибку по документу и продолжает
   обход остальных.
9. **Переменные окружения в `conftest.py` выставляются до первого импорта
   `api.*`** — настройки читаются на импорте модуля.
10. **Ruff считает `api` и `tests` своими** (`known-first-party`); без этого
    `--fix` переставляет импорты в тестах при каждом прогоне.
11. **`@computed_field` над `@property` mypy не поддерживает** (`prop-decorator`).
    Это рекомендованный pydantic способ отдать производное поле, поэтому в
    `RecordResponse` стоит точечный `# type: ignore[prop-decorator]`.
12. **`ASGITransport` не выполняет lifespan.** Фикстура `client` поднимает
    приложение без событий запуска, поэтому фоновый ролловер в тестах эндпоинтов
    не работает — и не мешает им. Его цикл проверяется отдельно
    (`tests/unit/test_rollover_loop.py`), а смена месяца — через сервис.
13. **`RolloverLoop.stop()` до первого прохода отменяет и первый проход**: цикл
    проверяет событие остановки до вызова. В работе это незаметно, но тест обязан
    дождаться прохода, прежде чем останавливать.

---

## 12. Что осталось неиспользованным

- `ExternalServiceError` (502) объявлен, но не выбрасывается: в api по-прежнему
  нет ни одного внешнего вызова. В `google_sheets_service` эту роль играет свой
  `GoogleApiError` — тащить исключение api в сервис, который его не импортирует,
  было бы связыванием на ровном месте.
- `Page[T]` объявлен, но пагинация нигде не нужна: каждый запрос ограничен одним
  документом и одним учётным месяцем. Использовать, только если появится
  выборка, способная вырасти.
- `BaseRepository.list()` не вызывается ни из одного репозитория — предназначен
  для будущих доменов. `delete()` (физическое удаление) с появлением
  `/check_del` используется: `CheckService.delete_check` убирает неразобранный
  чек насовсем, потому что мягко удалённое сырьё не нужно никому.
- `AccessRole.READER` не используется: доступ выдаётся на запись, потому что
  пользователь правит справочники прямо в таблице.
