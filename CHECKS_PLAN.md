# Добавление чеков: Mini App + `checks_service`

## Контекст

В переписанной версии проекта чеки — единственная непере­несённая часть старого бота.
На стороне `api` уже есть кэш `cashed_records` и запись разобранного чека
(`POST /checks/commit`), но **входа нет**: таблица `check_queue_items` хранит только
сырую строку, наполнять её нечем (старый Telethon-слушатель отключён), и `/check`
всегда отвечал бы «чеков нет».

Задача этого шага — сделать вход: Telegram Mini App, который сканирует QR-код чека,
получает по нему расшифровку и сохраняет чек в БД. Разбор чека (типы товаров,
категории, запись операций) в этот шаг **не входит** — бот не трогаем вовсе.

Ключевое требование заказчика: форматы QR-кодов будут разными (сейчас ФНС РФ, позже
сербские фискальные чеки с другими идентификаторами и другим источником расшифровки).
Поэтому на этапе добавления сохраняется **вся сырая информация и тип чека**, а
интерпретация откладывается до этапа разбора.

## Принятые решения

| Решение | Выбор и почему |
|---|---|
| Где живёт бэкенд Mini App | Новый сервис `checks_service` по образцу `ghostshelf_service` из эталона. `api` остаётся закрытым (`127.0.0.1`) и без единого внешнего вызова — оба записанных инварианта целы |
| Что пишем в БД | Только сырьё: `qr_raw`, `raw_payload`, `kind`. Ни даты, ни суммы, ни валюты в колонках — они форматно-специфичны |
| Дедупликация | Колонка `external_key`, содержимое вычисляет парсер формата (ФНС: `fn:fd:fp`). UNIQUE `(spreadsheet_id, kind, external_key)` — БД не знает ни одного формата, но дубль невыразим |
| Момент расшифровки | После нажатия «Добавить». Плашка строится из самой QR-строки, без внешнего вызова |
| Отказ внешнего сервиса | Ошибка пользователю, в БД не пишем ничего. Отсюда: ни статусов, ни фонового дозабора, чек в БД всегда полный |
| Доступ | Подпись `initData` (HMAC токеном бота) + свежесть `auth_date` + тот же `ALLOWED_TELEGRAM_IDS`, что у бота — чтобы посторонний не жёг платный лимит proverkacheka |
| Сканер | `Telegram.WebApp.showScanQrPopup` — ноль зависимостей и ноль возни с разрешениями камеры. Следствие: приложение только мобильное, на Telegram Desktop сканера нет |
| Распознавание формата | На сервере, отдельным `POST …/preview`. Фронт не знает ни одного формата: сербский добавится без правки JS |
| Точка расширения | `QrParser` (строка → реквизиты, чистая функция) и `ReceiptFetcher` (реквизиты → payload, весь I/O) — раздельно, связывает реестр |
| `check_queue_items` | Удаляется целиком вместе с эндпоинтами, репозиторием, ветками сервиса, тестами и параметром `check_id` |
| Публикация | Caddy на 80/443 (порты свободны, публичный IPv4 `185.239.49.175`), имя `185.239.49.175.sslip.io`, сертификат Let's Encrypt автоматом. Он же раздаёт статику Mini App — один origin, без CORS и mixed content. GitHub Pages не используется |
| Запуск Mini App | Menu Button в BotFather. Код `telegram_bot` не меняется ни строкой |
| Раскладка репозитория | `git worktree` в `/root/new_version`, ветка `new_version`, проект в **корне** ветки (без обёртки `new_version/`) |

## Что делаем

### 0. Перенос в worktree

`git worktree add /root/new_version -b new_version` от текущего HEAD, затем перенести
содержимое `Cost_accounting_bot/new_version/` в корень нового рабочего дерева и сделать
первый коммит. Секреты уже закрыты gitignore (`env/*.env`, `secrets/`, `google-sa.json`) —
проверить `git status` перед коммитом, репозиторий публичный.

Осторожно: `docker compose` этого проекта сейчас поднят из
`/root/Cost_accounting_bot/new_version`. Переносить содержимое стоит после
`docker compose down`, иначе bind-mount'ы останутся висеть на старых путях. Имя
compose-проекта после переезда сохранится (`new_version` — по имени директории).
`.venv` копировать не нужно: внутри абсолютные пути, восстанавливается `uv sync`.

**Отдельно и до пуша:** в `.git/config` origin-URL содержит GitHub-токен открытым
текстом. Отозвать токен, перейти на SSH или credential helper.

### 1. `api` — новый домен `checks`, старая очередь под нож

Порядок из `docs/API_machine.md` §10.

Добавляется:

- `api/enums/check_kind.py` — `CheckKind(StrEnum)`, значение `RU_FNS`; строка в `api/enums/__init__.py`
- `api/orm/check.py` — `CheckORM`, таблица `checks`: `spreadsheet_id` (FK CASCADE),
  `kind` (нативный enum), `qr_raw` Text, `external_key` Text, `raw_payload` JSONB,
  `fetched_at` TIMESTAMPTZ; `UniqueConstraint(spreadsheet_id, kind, external_key)`,
  индекс `(spreadsheet_id, id)`. Миксины `PkMixin`, `TimestampMixin` — как в
  `api/orm/cashed_record.py`
- `api/domain/check.py`, `api/mappers/check_mapper.py`, `api/repositories/check_repository.py`
  (`add`, `get_by_external_key`, `list_by_spreadsheet`)
- `api/requests/checks/save_check_request.py`, `api/responses/checks/check_response.py`
- `POST /spreadsheets/{id}/checks` → 201, дубль → 409

Правится:

- `api/services/check_service.py` — убрать `list_queue`/`enqueue`/`delete_from_queue`,
  добавить `save(...)`. Дубль ловится и как предварительная проверка, и как
  `IntegrityError` в обработчике — иначе гонка двух одновременных сканов даст 500
- `api/routers/checks.py` — минус три эндпоинта очереди, плюс один
- `commit_check` и `CommitCheckRequest` — убрать `check_id` и снятие с очереди
- `api/dependencies/repositories.py`, `services.py`, `api/orm|domain|mappers|repositories/__init__.py`

Удаляется: `check_queue_item.py` из `orm`/`domain`/`mappers`, `check_queue_repository.py`,
`responses/checks/check_queue_item_response.py`, `tests/repositories/test_check_queue_repository.py`.

Миграция (одна ревизия, вручную дописать после autogenerate — см. §11.1 «Грабли»):
`CREATE TYPE check_kind` → `CREATE TABLE checks` → `DROP TABLE check_queue_items`;
`downgrade` в обратном порядке, `DROP TYPE` строго после таблиц.

### 2. `checks_service` — новый сервис

Структура по образцу `google_sheets_service` и `/root/sales_analysis/ghostshelf_service`:

```
checks_service/
  main.py                 create_app() + lifespan: клиенты создаются здесь и закрываются
  config.py               pydantic-settings, env/checks_service.env
  constants.py  logging.py
  exceptions.py           ChecksError → FormatNotSupportedError / ReceiptFetchError /
                          ApiError + register_exception_handlers
  auth/init_data.py       разбор и проверка initData: HMAC-SHA256 с ключом
                          HMAC("WebAppData", bot_token), затем возраст auth_date
  auth/dependencies.py    Depends → telegram_id, 401/403
  formats/base.py         Protocol QrParser (matches / kind / parse → Credentials +
                          external_key + preview) и ReceiptFetcher (fetch → payload)
  formats/registry.py     подбор парсера по строке, kind → fetcher
  formats/ru_fns/parser.py    t, s, fn, i→fd, fp, n; external_key = "fn:fd:fp"
  formats/ru_fns/fetcher.py   proverkacheka.com
  main_api/http.py        ApiHttpClient — копия паттерна gsheets
  main_api/spreadsheets.py    GET /spreadsheets/by-telegram/{id}
  main_api/checks.py          POST /spreadsheets/{id}/checks
  services/check_intake.py    оркестрация preview и сохранения
  routers/system.py       /health
  routers/mini_app.py     POST /api/v1/mini-app/checks/preview
                          POST /api/v1/mini-app/checks
```

Пример QR-строки, которую разбирает `ru_fns`:

```
t=20260725T1507&s=1214.95&fn=7384440901402798&i=145&fp=698610272&n=1
```

Фетчер ФНС повторяет старый `bot/check_wrapper/utils.py`: POST на
`PROVERKACHEKA_BASE_URL` телом `{token, fn, fd, fp, t, s}` (`fd` — это `i` из QR).
Отличия от старой версии, и они существенные:

- **явный таймаут** — старый `requests.post` без таймаута в асинхронном коде вешал
  весь бот на зависшем proverkacheka;
- **проверка `code` в ответе** — старая версия отдавала тело дальше не глядя;
- **никакого LLM** — реквизиты берутся регуляркой из QR-строки. Старая версия просила
  модель вытащить ФН/ФД/ФП из текста и переклеивала дату строковыми операциями;
- дата в QR (`t=20260725T1507`) уже в нужном формате, переклейка не нужна.

`raw_payload` — ответ внешнего сервиса **целиком**, как пришёл. Суммы в копейках не
трогаем: на этапе разбора конвертировать только `Decimal(cents) / 100`; старый
`product["sum"] / 100` давал float, что запрещено инвариантом «деньги — `Decimal`».

### 3. `mini_app/` — статика

Четыре файла без сборщика: `index.html`, `app.js`, `styles.css`, `config.js`
(единственная строка с адресом бэкенда). Тексты русские, цвета — из
`var(--tg-theme-*)`.

Поток: `WebApp.ready()` → «Сканировать чек» → `showScanQrPopup` → `closeScanQrPopup` →
`POST …/preview` (initData в заголовке `Authorization: tma <initData>`) → плашка →
«Добавить» / «Отмена» → `POST …/checks` → результат.

Состояния плашки: чек распознан (для ФНС — с датой и суммой из QR) · формат не
поддерживается · чек уже добавлен · чек не найден во внешнем сервисе · таблица не
создана · доступ запрещён.

### 4. Развёртывание

В `docker-compose.yml` два сервиса:

- `checks-service` — `127.0.0.1:8012:8000`, `env/checks_service.env`
  (`TELEGRAM_BOT_TOKEN`, `ALLOWED_TELEGRAM_IDS`, `API_BASE_URL`,
  `PROVERKACHEKA_BASE_URL`, `PROVERKACHEKA_API_TOKEN`, таймауты), healthcheck как у
  остальных, `depends_on: api healthy`;
- `caddy` — `80:80`, `443:443`, `./mini_app:/srv/mini_app:ro`, тома под сертификаты.

```
185.239.49.175.sslip.io {
    handle /api/* { reverse_proxy checks-service:8000 }
    handle        { root * /srv/mini_app
                    file_server }
}
```

Плюс `dockerfiles/checks_service.Dockerfile` (копия gsheets-варианта), пакет в
`[tool.hatch.build.targets.wheel]`, `src` и `known-first-party` в ruff-конфиге.

Ручные шаги пользователя: BotFather → Menu Button → `https://185.239.49.175.sslip.io/`.

### 5. Тесты и документация

По образцу существующих 330 тестов:

- `tests/checks_service/unit/` — парсер ФНС (валидные строки, мусор, чужой формат,
  `external_key`), реестр, проверка `initData` (валидная подпись, подделанная,
  протухшая)
- `tests/checks_service/test_mini_app.py` — роутеры с фейковым фетчером и фейковым
  api-клиентом (фейки — как `tests/google_sheets_service/fakes.py`)
- `tests/repositories/test_check_repository.py`, `tests/db/test_schema_constraints.py`
  (+UNIQUE), обновлённые `tests/services/test_check_service.py` и `tests/api/test_checks.py`
- `docs/CHECKS_machine.md` — карта нового сервиса; правки в `API_machine.md`
  (дерево, таблицы, поверхность api, §9) и `BOT_machine.md` §10

## Проверка

```bash
cd /root/new_version
uv run ruff check . && uv run mypy api checks_service google_sheets_service telegram_bot tests
uv run pytest                                  # нужен Postgres 16 на :5544
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
docker compose up -d --build
curl -s localhost:8012/health
curl -s https://185.239.49.175.sslip.io/       # статика и сертификат
```

Затем сквозная проверка вручную: `/preview` и `/checks` с подписанным тестовым
`initData` (подпись генерируется тем же кодом, что и проверяется — тестовая утилита),
после этого реальный скан чека с телефона через Menu Button бота, и `SELECT` в
`checks` — строка одна, `raw_payload` не пустой; повторный скан того же чека
отвечает «уже добавлен» и второй строки не создаёт.
