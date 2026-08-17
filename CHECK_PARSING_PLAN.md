# Разбор чека: `checks` → типы → категории → операции реестра

## Контекст

Вход чеков сделан: `checks_service` + `mini_app` кладут в таблицу `checks` сырьё —
QR-строку, вид формата и ответ внешнего сервиса целиком. Интерпретации нет.
Это последняя непереснесённая часть старого бота и последний пункт
`API_machine.md` §9 (шаг 4).

Задача: превратить сырьё в операции реестра. Из `raw_payload` достать позиции,
назначить каждой тип товара с опорой на кэш `cashed_records`, сопоставить типы
категориям и записать всё одной транзакцией через `POST /checks/commit`.

Ветка чеков в старой версии была нерабочей целиком (`AddCheck.py:227` —
`ValueError` на первом же чеке с незакэшированным товаром). Список того, что
нельзя повторять, — `BOT_machine.md` §10.

## Принятые решения

| Решение | Выбор |
|---|---|
| Где живёт диалог | **В боте**, FSM. Mini App остаётся только входом |
| Признак разбора | `checks.processed_at` + `records.check_id` (составной FK) |
| Роль LLM | Два вызова: типы для незнакомых товаров, затем категории для новых типов |
| Где клиент LLM | `telegram_bot/ai/` |
| Дата операций | День разбора, период текущий — `commit_check` не меняется |
| Гранулярность | Позиция = операция |
| Нулевые позиции | Пишутся как есть: `CHECK amount <> 0` снимается, `CheckItem.amount` → `ge=0` |
| Канарейка на разбор | Σ позиций сверяется с `totalSum`; расхождение — отказ, чек не записывается |
| Возвраты (`operationType ≠ 1`) | Отказ с внятным текстом |
| Правка кэшированного типа | Кэш перезаписывается, бот говорит «Запомнил: молоко → молочка» |
| Формат правок | Строки «1,3 - молочка» + кнопка «Готово» |
| Поверхность | Одна точка входа `/check` (очередь с самого старого), плюс `/check_skip`, `/check_del` |
| Пропуск | Ничего не сохраняет: чек остаётся неразобранным и вернётся в следующей сессии |
| Удаление | Без подтверждения, физическое; после обоих — следующий чек |
| Нераспознанное | «НеопределенныеТраты», `product_type = NULL` |
| Тип занят другой категорией | 409 с указанием чужой категории, чек не записывается |
| Отказ модели | Отказать и предложить повторить позже |
| `records.check_json` | Колонка удаляется — с появлением `check_id` это дубль |

---

## 1. `api` — миграция и домен чеков

Порядок из `API_machine.md` §10. Одна ревизия, после autogenerate **прочитать
глазами** (§11.1).

**Миграция:**

- `checks.processed_at` TIMESTAMPTZ NULL; партиальный индекс
  `(spreadsheet_id, id) WHERE processed_at IS NULL` — писать руками и дублировать
  в `__table_args__`, autogenerate его не видит (§6.9);
- `UNIQUE (id, spreadsheet_id)` на `checks` — цель составного FK, ровно как
  `periods` (`api/orm/period.py`);
- `records.check_id` BIGINT NULL + `ForeignKeyConstraint(["check_id",
  "spreadsheet_id"], ["checks.id", "checks.spreadsheet_id"])`,
  **`deferrable=True, initially="DEFERRED"`** — по той же причине, что у
  `periods`/`categories`/`sources`: при удалении документа порядок каскадов не
  определён (§4). `ondelete` не ставить: `/check_del` разрешён только для
  неразобранного чека, у которого операций нет по определению;
- `DROP CONSTRAINT` для `amount_not_zero` на `records`;
- `DROP COLUMN records.check_json`.

`downgrade` — в обратном порядке.

**Правится:**

- `api/core/types.py` — `NonNegativeMoneyDecimal` (`ge=0`) рядом с
  `PositiveMoneyDecimal`. `CreateRecordRequest.amount` остаётся `gt=0`: строгость
  держим на пути записи, а не в таблице;
- `api/orm/check.py`, `api/orm/record.py`, `api/domain/check.py`,
  `api/domain/record.py`, `api/domain/check_item.py`, мапперы — новые поля,
  `check_json` вычищается везде (`CheckItem`, `CommitCheckRequest`,
  `CreateRecordRequest`, `RecordService.create`);
- `api/responses/records/record_response.py` — `from_check` считается по
  `check_id is not None` (точечный `# type: ignore[prop-decorator]` уже стоит).
  **Отменено следующей правкой** (`e5a1f83b2c47`): наружу выдаётся сам
  `check_id`, а в колонке `Check` реестра печатается номер чека — расшифровка
  теперь лежит строкой на отдельном листе-архиве, и галочке там нечего делать;
- `api/repositories/check_repository.py` — `list_by_spreadsheet(spreadsheet_id,
  *, unprocessed=False)`, `get_for_spreadsheet(check_id, spreadsheet_id)`,
  `mark_processed(check_id)` (через `RETURNING`, не перечитыванием — §11.5),
  `delete(check_id)`;
- `api/services/check_service.py`:
  - `list_checks` получает `unprocessed`,
  - `delete_check(spreadsheet_id, check_id)` — 404 «check», 409
    `check_already_processed`, если `processed_at` не пуст,
  - `commit_check` принимает `check_id`: проверяет принадлежность документу и
    `processed_at IS NULL` (409 `check_already_processed`), проставляет
    `records.check_id` и `checks.processed_at` **в той же транзакции**, что и
    операции. Инвариант «ни одна часть не уцелеет без остальных» распространяется
    и на отметку,
  - `_assign_product_types` — предварительная проверка «тип уже закреплён за
    другой категорией» **плюс** перехват `IntegrityError` (гонка с импортом
    справочника), обе ветки → `ConflictError` с
    `details={"reason": "product_type_taken", "product_type": ..., "category": ...}`
    и `await self._session.rollback()` перед подъёмом, как в `save`;
- `api/routers/checks.py` — `?unprocessed=`,
  `DELETE /spreadsheets/{id}/checks/{check_id}` (204), `check_id` в
  `CommitCheckRequest`;
- `api/dependencies/*` правок не требуют.

---

## 2. `telegram_bot/ai/` — клиент модели

По образцу `telegram_bot/api_client/http.py`: один класс, вся работа с внешним
сервисом внутри, наружу — доменные модели и типизированные ошибки.

- `ai/client.py` — `AiClient` на `openai.AsyncOpenAI`,
  `response_format={"type": "json_object"}`, **явный таймаут**;
- `ai/errors.py` — `AiUnavailableError` (сеть, таймаут, 5xx) и
  `AiResponseError` (нераспознаваемый JSON, ответ не той формы). Обе → «Подсказки
  недоступны, попробуйте позже», чек остаётся неразобранным, FSM чистится;
- `ai/models.py` — pydantic-модели ответа. Ответ модели **валидируется схемой**,
  а не обходится словарём: `AddCheck.py:227` (`for x, id in answer:`) падал
  `ValueError`-ом мимо обработчика именно потому, что форму ответа никто не
  проверял;
- `resources/prompts/*.txt` — переносятся из
  `bot/datafiles/prompts/get_TYPES_*` и `get_CATEGORIES_*`, читаются с явным
  `encoding="utf-8"`, как остальные ресурсы бота;
- `config.py` — `openai_api_key`, `openai_base_url`, `openai_model`,
  `ai_timeout_seconds`, `ai_temperature`; `env/telegram_bot.env.example`.

Промпт «получить реквизиты из текста чека» **не переносится**: реквизиты
разбирает `checks_service/formats/ru_fns/parser.py` из QR-строки.

---

## 3. `telegram_bot` — извлечение позиций

`telegram_bot/checks/extractor.py` — чистая функция «`raw_payload` → позиции»,
без ввода-вывода, проверяется таблицей примеров.

- позиции: `data.json.items`, `name` и `sum`;
- **суммы — копейки**: `Decimal(item["sum"]) / 100`. Ни одного `float`; старый
  `product["sum"] / 100` давал `float` (`API_machine.md` §6.2);
- `operationType` ≠ 1 → `ReceiptNotSupportedError` («Чеки-возвраты пока не
  поддерживаются, внесите вручную»), бот предлагает `/check_del`;
- **сверка итога**: `Σ items[].sum` против `data.json.totalSum` (обе величины —
  копейки, сравнение целочисленное). Расхождение → `ReceiptMismatchError`, чек не
  записывается, в журнал уходят обе суммы. Это и есть канарейка на «прочитали не
  то поле»; строить её на нулевой сумме нельзя — нулевая цена товара законна;
- `totalSum` отсутствует → отступаем на `s=` из `qr_raw` (рубли, `Decimal`);
- нет `data.json.items` вовсе (чек сохранён, но payload неожиданной формы) →
  та же внятная ошибка, не `KeyError`.

---

## 4. `telegram_bot` — диалог разбора

**Состояния** (`states.py`): `CHECK_TYPES`, `CHECK_CATEGORIES`, `CHECK_SOURCE`.

**FSM-данные** (`enums.py`, `FsmDataKeys`): `CHECK_ID`, `CHECK_ITEMS`,
`SKIPPED_CHECK_IDS`, `SAVED_COUNT`. Всё промежуточное — только здесь: словаря
`self.temp_data[user_id]` на экземпляре команды быть не должно (§4.3).
`SKIPPED_CHECK_IDS` — причина, по которой очередь не зацикливается: пропущенный
чек остаётся `processed_at IS NULL` и иначе возвращался бы «следующим» бесконечно.

**Команды** (`commands/check.py`, `check_skip.py`, `check_delete.py`):

- `/check` — берёт старейший неразобранный, не входящий в `SKIPPED_CHECK_IDS`.
  Шапка: магазин, дата, итог. Затем три стадии;
- `/check_skip` — кладёт текущий id в `SKIPPED_CHECK_IDS`, показывает следующий.
  Ничего не пишет;
- `/check_del` — `DELETE .../checks/{id}` без подтверждения, показывает следующий;
- `/cancel` — существующая команда, выходит из разбора совсем;
- конец очереди: «Чеки закончились. Записано: N. Пропущено: M — они остались в
  списке, `/check` покажет их снова».

**Стадия 1 — типы** (`CHECK_TYPES`). Товары из `cashed_records` получают тип без
модели. Остальные уходят в первый вызов. Вывод — нумерованный список. Правка:
строки «1,3 - молочка», разбирает `parsers/check_parser.py` и поднимает
`ParseError` с готовым русским текстом (протокол `{"status": ...}` из старой
версии не воспроизводится, §3). Кнопка «Готово» — переход дальше.

**Стадия 2 — категории** (`CHECK_CATEGORIES`). Тип определяет категорию
детерминированно: `UNIQUE (spreadsheet_id, product_type)` на
`category_product_types`. Модель зовётся **только** для позиций с новым типом.
Правка — теми же строками, категория ищется `AssociationMatcher` по псевдонимам.
Позиция, оставшаяся без категории, → «НеопределенныеТраты», `product_type = NULL`.

**Стадия 3 — счёт** (`CHECK_SOURCE`). Один счёт на весь чек, ввод псевдонимом,
подбор тем же `AssociationMatcher`. Затем `POST /checks/commit` с `check_id`.

**Итог.** «Записано операций: N», строки «Запомнил: молоко → молочка» по каждой
позиции, чей тип отличается от лежавшего в кэше, и «Пропущено бесплатных
позиций» не выводится — нулевые позиции теперь пишутся.

**Правки не теряются.** Бот шлёт в `commit` итоговый тип по **каждой** позиции,
включая взятые из кэша, — `CashedRecordRepository.upsert` переучивает сам. В
старой версии правка типа у уже распознанного товара никуда не записывалась
(`BOT_machine.md` §10).

**Кнопки.** В `callback_data` кладётся `check_id`, обработчик фильтруется по
состоянию. Без этого повторяется старый баг: кнопка от предыдущего чека остаётся
живой и применяется к текущему.

**Регистрация** (`main.py`). Порядок существенный (§9.3): `/cancel` → «команда
посреди диалога» → шаги диалога → команды вне состояний. `/check_skip` и
`/check_del` регистрируются **внутри** состояний разбора, `/check` — вне.
В `_MENU` попадают все три: в меню только зарегистрированное (§9.4).

**Клиент api** (`api_client/checks.py`) — `ChecksClient`: `list_unprocessed`,
`delete`, `cashed_records`, `commit`. Модели в `api_client/models.py`.
`errors.py` — тексты для новых 409 (`product_type_taken`,
`check_already_processed`).

---

## 5. Тесты

- `tests/unit/test_check_extractor.py` — позиции, копейки → `Decimal`, нулевая
  позиция, `operationType = 2`, расхождение с `totalSum`, отсутствующий `items`;
- `tests/unit/test_check_parser.py` — «1,3 - молочка», мусор, несуществующий id;
- `tests/telegram_bot/test_check_command.py` — очередь, пропуск и возврат
  пропущенного, удаление, правка кэшированного типа доезжает до `commit`,
  отказ модели не роняет диалог. Фейк `AiClient` и фейк `ApiGateway`;
- `tests/repositories/test_check_repository.py` — `unprocessed`,
  `mark_processed`, `delete`;
- `tests/db/test_schema_constraints.py` — составной FK `records → checks`,
  отсутствие `amount_not_zero`, нулевая операция проходит;
- `tests/services/test_check_service.py` — `commit_check` ставит `processed_at` и
  `check_id`, повторный commit → 409, занятый тип → 409, удаление разобранного
  чека → 409;
- `tests/api/test_checks.py` — новые маршруты и параметр.

---

## 6. Документация

- `docs/CHECKS_machine.md` — §1 таблица шагов, §8 заменяется на карту разбора;
- `docs/BOT_machine.md` — §2 поверхность команд, §10 переписывается с «что
  дальше» на «как сделано», §4 пополняется инвариантами разбора. **Отдельно:**
  §1 утверждает «ни драйвера БД, ни ключей Google здесь нет» — теперь у бота есть
  ключ OpenAI, формулировку надо поправить честно, а не обойти;
- `docs/API_machine.md` — §2 дерево, §4 таблицы, §8 поверхность, §9 шаг 4
  «сделан», §12 (`check_json` больше не долг);
- `README.md` — строка про разбор.

---

## Проверка

```bash
cd /root/new_version
uv run ruff check . && uv run mypy api checks_service google_sheets_service telegram_bot tests
uv run pytest                                   # нужен Postgres 16 на :5544
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
docker compose up -d --build && curl -s localhost:8010/health
```

Сквозная проверка вручную:

1. отсканировать чек через Mini App с телефона, убедиться в строке `checks`;
2. `/check` в боте — шапка, список позиций, предложенные типы;
3. поправить одну позицию строкой «2 - молочка», нажать «Готово», пройти
   категории и счёт;
4. `SELECT` в `records`: N строк, `check_id` заполнен; `SELECT processed_at FROM
   checks` — не пуст; `cashed_records` содержит правку;
5. `/check` снова — этого чека в очереди нет;
6. отсканировать второй чек, `/check_skip`, затем `/cancel`, затем `/check` —
   пропущенный чек показывается снова;
7. `/check_del` на третьем — строка исчезает из `checks`;
8. проверить лист операций и статистики в Google-таблице после прохода
   `google_sheets_service`.
