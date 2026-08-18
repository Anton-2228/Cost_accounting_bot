# Мягкое удаление чека вслед за последней его операцией

## Контекст

Сегодня удаление всех операций, вышедших из чека, оставляет сам чек в базе
навсегда. Он разобран (`processed_at` заполнен), поэтому в очередь `/check` не
вернётся; он занимает `external_key`, поэтому ту же бумажку нельзя отсканировать
заново; и он продолжает висеть строкой на листе-архиве месяца, хотя в реестре от
него ничего не осталось. Единственный способ убрать его — руками в SQL:
`/check_del` разобранный чек не удаляет (409).

Нужно: когда умирает последняя живая операция чека, чек умирает следом. Удаление
чека при этом становится **мягким** — как у операций: строка и `raw_payload`
остаются, из всех выборок чек пропадает.

### Что это отменяет

Два принятых ранее решения, оба задокументированы и оба покрыты тестами:

1. `CheckRepository.list_processed_for_period` (`api/repositories/check_repository.py:88`)
   намеренно считает мягко удалённые операции — «удаление последней операции
   иначе молча вынесло бы чек из архива». Правило заменяется на: операции
   учитываются независимо от `deleted_at`, но **сам чек** должен быть жив. Тест
   `tests/repositories/test_check_repository.py:195`.
2. «Удаление чека физическое, сырьё незачем хранить удалённым»
   (`CheckService.delete_check`, `api/services/check_service.py:110`; тест
   `tests/repositories/test_check_repository.py:222`). Теперь у таблицы один
   механизм удаления — мягкий, и `/check_del` переходит на него тоже.

### Решения, принятые в этом разговоре

| Вопрос | Выбор |
|---|---|
| Как исчезает чек | Мягко: `deleted_at`, как у операций |
| Повторный скан той же бумажки | Принимается как **новый** чек: уникальность `external_key` становится частичной (`WHERE deleted_at IS NULL`) |
| `/check_del` | Тоже мягкое удаление |
| Старые осиротевшие чеки | Ничего не делаем — база будет пересоздана |
| Сообщение бота | Никакого: удаление чека — следствие, а не событие. `telegram_bot/` и контракт API не меняются вовсе |
| `/check_del` для разобранного чека | По-прежнему 409: разобранный чек убирают, удаляя его операции |

## Изменения

Всё — внутри `api/`.

### 1. Схема

`api/orm/check.py` — `CheckORM` получает `SoftDeleteMixin` (`api/db/mixins.py`,
уже используется `RecordORM`, `TransferORM`, справочниками). В `__table_args__`:

- `UniqueConstraint("spreadsheet_id", "kind", "external_key")` → частичный
  уникальный `Index(..., postgresql_where="deleted_at IS NULL")`. Имя менять не
  нужно, но тип объекта меняется: `UniqueConstraint` частичным быть не умеет.
- `ix_checks_unprocessed` → `postgresql_where="processed_at IS NULL AND deleted_at IS NULL"`:
  очередь разбора не должна показывать удалённое.
- `UniqueConstraint("id", "spreadsheet_id")` **не трогать** — на него смотрит
  составной FK `fk_records_check_id_checks`.

Докстринг класса переписать: сказать, что удаление мягкое и почему
(`raw_payload` — единственный след покупки, а операции, вышедшие из чека, тоже
удаляются мягко и продолжают на него ссылаться); объяснить частичную
уникальность (жить может только один экземпляр бумажки, история — сколько
угодно).

`api/orm/record.py` — поправить абзац про `check_id`: фраза «удалять разрешено
только неразобранный чек, у которого операций нет по определению» больше не
верна. Отсутствие `ondelete` теперь обосновано иначе: чек физически не удаляется
никогда, ссылка не может повиснуть.

### 2. Миграция

Новый файл в `api/alembic/versions/`, `down_revision = "e5a1f83b2c47"` (текущий
head). Содержимое:

- `ADD COLUMN deleted_at TIMESTAMPTZ NULL` в `checks`;
- `DROP CONSTRAINT uq_checks_spreadsheet_id_kind_external_key` +
  `CREATE UNIQUE INDEX ... WHERE deleted_at IS NULL`;
- пересоздание `ix_checks_unprocessed` с новым условием.

Откат — обратные операции; данных не переносим (бэкфилла нет по решению выше).
Шапку файла оформить прозой с объяснением, как остальные миграции проекта.

### 3. Домен и маппер

`api/domain/check.py` — поле `deleted_at: datetime | None = None`.
`api/mappers/check_mapper.py` — проброс в обе стороны, ровно как в
`api/mappers/record_mapper.py:27,45`. `CheckResponse` не трогаем: наружу
удалённые чеки не отдаются вовсе, показывать метку некому.

### 4. Репозитории

`api/repositories/check_repository.py` — во все четыре выборки добавить
`CheckORM.deleted_at.is_(None)`: `get_by_external_key`, `get_for_spreadsheet`,
`list_by_spreadsheet`, `list_processed_for_period`. Туда же — условие в
`mark_processed`, иначе разбор смог бы отметить удалённый чек. Это существенно, а
не гигиена: без фильтра в `get_for_spreadsheet` `commit_check` записал бы
операции в удалённый чек, а `save` получил бы 409 на бумажку, которую только что
разрешили сканировать заново.

Подстроку про мягко удалённые операции в докстринге `list_processed_for_period`
переписать под новое правило.

`api/repositories/record_repository.py` — новый метод `exists_by_check(check_id)`
по образцу `exists_by_source` (`record_repository.py:114`): живые операции с
таким `check_id`.

### 5. Сервисы

`api/services/record_service.py`, метод `delete` — после `soft_delete` операции и
чистки кэша: если у операции был `check_id` и `exists_by_check` вернул `False`,
мягко удалить чек тем же моментом времени (`now_in_timezone(spreadsheet.timezone)`,
уже вычисляется выше) и добавить к ключам перерисовки
`(spreadsheet_id, REDRAW, SheetTarget.CHECKS, record.period_id)` — лист-архив
месяца потерял строку. Всё внутри той же транзакции, `_commit` остаётся один.

Для этого в `RecordService` добавляется `checks: CheckRepository` — конструктор и
`get_record_service` в `api/dependencies/services.py:80`.

`api/services/check_service.py`, `delete_check` — `self._checks.soft_delete(check.id, at=datetime.now(UTC))`
вместо `delete`. Проверка `processed_at is not None → 409` остаётся: разобранный
чек убирают удалением его операций, и два входа в одно состояние заводить не
нужно. Докстринг переписать.

## Тесты

`tests/repositories/test_check_repository.py`:

- существующий тест архива (строка 195) переписать: две операции, удалена одна —
  чек остаётся в архиве. Исходное намерение теста («мягкое удаление операции не
  выносит чек из архива») сохраняется, меняется только условие исчезновения.
- новый: чек с `deleted_at` из архива и из `list_by_spreadsheet` пропадает.
- `test_check_is_deleted_physically` (строка 222) → мягкое: строка остаётся,
  повторный вызов возвращает `False`.
- новый: пока чек жив, второй с тем же `(spreadsheet_id, kind, external_key)`
  падает `IntegrityError`; после мягкого удаления — вставляется.

`tests/services/test_record_service.py`:

- удаление последней операции чека помечает чек удалённым и ставит задачу
  `CHECKS` на период;
- удаление одной из двух — чек жив, задачи `CHECKS` нет;
- удаление операции без `check_id` ничего лишнего не делает.

`tests/services/test_check_service.py`:

- `commit_check` по удалённому чеку — 404;
- `save` той же бумажки после удаления — успех, новый id;
- `delete_check` разобранного — по-прежнему 409.

## Документация

Проект документирует решения, а не код, поэтому обновляются те места, где
записано отменяемое:

- `docs/CHECKS_machine.md` — жизненный цикл чека, §8;
- `docs/API_machine.md` — раздел про `checks` и `/checks/{id}`;
- `docs/BOT_machine.md` — абзац про `/check_del` (удаление стало мягким;
  поведение команды не изменилось);
- `telegram_bot/commands/check_delete.py` — докстринг упоминает физическое
  удаление.

## Проверка

```bash
uv run ruff check .
uv run mypy api checks_service google_sheets_service telegram_bot tests
docker run -d --name pg-test -e POSTGRES_PASSWORD=test -p 5544:5432 postgres:16
uv run pytest
```

Миграция накатывается и откатывается на пустой базе:

```bash
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Сквозной сценарий на живом стеке (`docker compose up -d --build`):

1. Mini App — отсканировать чек, `/check` в боте — разобрать.
2. `curl -s localhost:8010/spreadsheets/1/checks?period_id=<id>` — чек в архиве.
3. `/del <id>` на каждую операцию чека.
4. Тот же `curl` — чека нет; `curl -X POST localhost:8011/sync` — строка ушла с
   листа `Checks`.
5. Отсканировать ту же бумажку — принимается как новый чек и встаёт в очередь
   `/check`.
