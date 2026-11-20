# Архитектура

Adrobot — это тонкий веб-слой над Keitaro Admin API с собственной локальной PostgreSQL-копией кампаний, потоков и офферов. Backend полностью отделяет frontend от Keitaro: браузер никогда не знает API-ключ трекера и не делает запросы к Keitaro напрямую.

## Компоненты

| Компонент | Технология | Что делает |
|---|---|---|
| `frontend` | React 18, Vite, TypeScript, nginx 1.27 | две вкладки UI, Basic auth в памяти страницы, вызовы `/api/*`, уведомления и подтверждения |
| `backend` | FastAPI, Uvicorn, Python 3.12 | HTTP API, авторизация, бизнес-логика, единственный клиент Keitaro |
| `db` | PostgreSQL 16 | локальная копия кампаний, потоков, офферов и логов синхронизации |
| Alembic | миграции `0001` → `0003` | создание и эволюция схемы при старте backend |

Внешние зависимости: только Keitaro Admin API и PostgreSQL. Сторонних брокеров, очередей и фоновых воркеров нет: вся синхронизация происходит в HTTP-запросе.

Слои backend:

| Слой | Файлы | Ответственность |
|---|---|---|
| Точка входа | `app/main.py` | lifespan, `/healthz`, единый обработчик `AppError`, подключение `/api` с Basic auth |
| Конфигурация | `app/core/config.py`, `app/core/errors.py` | env-настройки, fail-closed проверка авторизации, формат ошибки |
| HTTP | `app/api/deps.py`, `app/api/{geo,keitaro,campaigns,flows}.py` | авторизация, DI, маршруты, request/response-схемы |
| Схемы | `app/schemas/*.py` | валидация входа и формат выхода |
| Сервисы | `app/services/*.py` | вся бизнес-логика и работа с Keitaro/БД |
| Данные | `app/db/database.py`, `app/db/models.py` | engine SQLAlchemy 2, ORM-модели и ограничения |

Отдельного слоя `repositories/` нет: SQLAlchemy-сессии создаются в `get_db()` и передаются в сервисы явно.

## Запрос на высшем уровне

```text
Браузер ── /api/* + Basic auth ──> nginx ──> FastAPI ──> сервис ──> PostgreSQL
                                                      │
                                                      └── KeitaroClient ──> Keitaro Admin API
```

Nginx проксирует только `/api/` и `/healthz`, остальные пути отдают статический bundle React. Backend напрямую доступен на `127.0.0.1:8000`; nginx — на `127.0.0.1:8080`.

`KeitaroClient` — единственная точка входа в Keitaro. Он:

- добавляет префикс `/admin_api/v1/` к `KEITARO_BASE_URL` и заголовок `Api-Key`;
- использует таймауты 30 с на запрос и 5 с на подключение;
- повторяет только GET до 3 попыток при сетевых ошибках и HTTP 5xx;
- нормализует ошибки в `KEITARO_AUTH`, `KEITARO_NOT_FOUND`, `KEITARO_VALIDATION`, `KEITARO_BAD_RESPONSE`, `KEITARO_UNREACHABLE`;
- никогда не кладёт ключ в ответ, сообщение об ошибке или лог.

## Сервисы

| Сервис | Назначение |
|---|---|
| `catalog_service.py` | домены, группы, источники, офферы; кэш `/offers` на 60 с, только активные офферы, список стран из `core/countries.json` |
| `keitaro_campaign_service.py` | список кампаний Keitaro для Editor; кэш на 30 с, локальный поиск по name/alias/ID, без `token` в ответе |
| `share_calculator.py` | чистая функция расчёта целых shares, `MIN_SHARE = 1`, total 100, largest remainder |
| `campaign_service.py` | Campaign Creator: создание кампании и двух потоков, компенсационная архивация, результат §3.6 |
| `sync_service.py` | чтение удалённого состояния, стабильные хэши потока, проверка структуры Creator, запись локальной копии |
| `editor_service.py` | чтение локальной копии, статусы, Fetch, защита от локальных изменений |
| `offer_service.py` | Add/Delete/Restore/PATCH офферов, пересчёт shares под блокировкой |
| `upload_service.py` | Upload потока, проверка конфликтов, partial/full PUT, контрольное чтение, recovery зависших отправок |

## Локальная модель

Таблицы создаются миграциями:

| Таблица | Назначение |
|---|---|
| `campaigns` | локальная карточка кампании Keitaro; `UNIQUE (keitaro_id)` |
| `campaign_flows` | потоки; `UNIQUE (keitaro_flow_id)`, `sync_status`, `revision`, `remote_hash`, `remote_payload JSONB` |
| `campaign_offers` | активные и удалённые офферы потока; `UNIQUE (flow_id, keitaro_offer_id)` |
| `sync_logs` | успешные и ошибочные операции Fetch/Upload |

Важные ограничения:

- `share` — целое число `0..100`;
- оффер либо активен (`is_active=true`, `deleted_at IS NULL`), либо в архиве (`is_active=false`, `deleted_at NOT NULL`);
- внешние ключи с `ON DELETE CASCADE`: потоки, офферы и логи удаляются вместе с кампанией;
- индексы по `(campaign_id)`, `(flow_id, is_active)` и логам.

Миграции:

- `0001_init.py` — пустая база;
- `0002_editor_tables.py` — четыре таблицы, ограничения и индексы;
- `0003_flow_remote_payload.py` — колонка `remote_payload JSONB` для fallback full PUT.

Текущая версия после старта: `0003 (head)`.

## Статусы и версии

`sync_status` потока принимает значения:

| Статус | Смысл |
|---|---|
| `synced` | локальная копия соответствует последнему Fetch/Upload |
| `modified` | есть локальные изменения, ещё не отправленные в Keitaro |
| `uploading` | Upload выполняется сейчас |
| `error` | последняя операция завершилась ошибкой |

`revision` увеличивается при каждой локальной мутации оффера. Upload запоминает `r0` на момент старта и в конце выставляет `synced`, только если revision не изменился. Иначе поток остаётся `modified`: правки во время отправки не считаются отправленными.

Статус кампании — наихудший среди видимых потоков: `error > uploading > modified > synced`.

## Campaign Creator

Последовательность `POST /api/campaigns`:

1. Валидация `name`, `geo`, ID справочников и офферов. Неактивные офферы не принимаются.
2. Расчёт равных целых shares для выбранных офферов.
3. Генерация случайного alias из 8 символов. При дубле alias возможно до 3 попыток; дубль имени не повторяется. При потере ответа POST выполняется поиск кампании по alias полным проходом GET `/campaigns`.
4. `POST /campaigns` с типом `position`, `cost_type=CPC`, `cost_currency=USD`, `cost_auto=true`. Если Keitaro просит `group_id` строкой, запрос повторяется со строкой.
5. `POST /streams`: redirect-поток `GEO to Google` с фильтром `country` accept и `action_options.url`, затем landings-поток `Offer` с офферами.
6. Контрольное чтение: ровно два активных потока, `schema` по порядку `redirect`, `landings`.
7. Атомарная запись локальной копии.

Ключевое решение: при ошибке создания потока или неверной структуре кампания сначала переименовывается (освобождаются `name` и `alias`), затем архивируется через `DELETE /campaigns/{id}`. При ошибке чтения Keitaro или записи в локальную БД кампания **не** архивируется — в результате возвращается `local_sync_failed` и предупреждение.

## Fetch

`POST /api/campaigns/fetch` и `POST /api/campaigns/{id}/fetch`:

1. Проверка, что нет потока в `uploading` (`BUSY`) и локальных правок (`LOCAL_CHANGES`, обходится `force=true`).
2. Сетевое чтение `GET /campaigns/{id}` и `GET /campaigns/{id}/streams` до захвата локальных блокировок. При сетевой ошибке локальные данные не меняются.
3. Блокировки campaign и потоков в стабильном порядке `ORDER BY id ... FOR UPDATE`, повторная проверка статусов и revision.
4. Атомарная замена полей кампании, потоков и офферов; `sync_status=synced`, `revision=0`.
5. Офферы со `state != active` попадают в `deleted_offers`. Потоки, исчезнувшие в Keitaro, получают `state=deleted` и скрываются из UI, но данные сохраняются.
6. successful Fetch пишет `SyncLog`, ошибка записи — `LOCAL_DB_ERROR` (500) с откатом транзакции.

## Локальные мутации офферов

Add/Delete/Restore/PATCH выполняются под `SELECT ... FOR UPDATE` на потоке, затем пересчитывают shares и увеличивают revision.

- **Add**: оффер из каталога или произвольный ID; новый оффер получает вес как среднее незакреплённых; дубль активного оффера — `DUPLICATE_OFFER`.
- **Delete**: мягкое удаление в `deleted_offers`; перед пересчётом все незакреплённые доли сбрасываются, поэтому `34/33/33` становится `50/50`, Fixed сохраняются.
- **Restore**: оффер возвращается как новый, прежние share и Fixed игнорируются.
- **PATCH share**: введённое число становится Fixed и «опорной» долей; остальные пересчитываются.
- **PATCH is_fixed=false**: снятие Fixed тоже вызывает пересчёт свободных долей заново.

`share_calculator` оперирует только целыми числами и не знает про БД/HTTP. Ошибки `INVALID_SHARES`, `FIXED_SUM_EXCEEDS_100`, `FIXED_SUM_MUST_BE_100`, `INFEASIBLE_SHARES` возвращаются до сохранения изменений.

## Upload

`POST /api/flows/{flow_id}/upload`:

1. Сетевые проверки до локальных блокировок: кампания активна, поток не изменился (`remote_hash`), иначе `REMOTE_CHANGED` или `CAMPAIGN_ARCHIVED`.
2. В одной транзакции: блокировка потока, проверка `BUSY`, наличие активных офферов, валидация shares, `sync_status=uploading`, фиксация `r0`.
3. Partial `PUT /streams/{id}` только с активными `offers`.
4. Контрольное чтение. Если хэш потока без offers изменился, отправляется полный `StreamRequestPut`, собранный из сохранённого `remote_payload` и свежих полей GET.
5. Ещё одно контрольное чтение подтверждает `offer_id`, `share` и `state`.
6. Финализация: `remote_hash`, `remote_payload`, `last_uploaded_at`, `SyncLog`, статус `synced` или `modified`.

При любой ошибке после перевода в `uploading` статус меняется на `error`, а сообщение пишется в `SyncLog`; локальные офферы и shares не меняются. При старте приложения `recover_stale_uploads()` переводит зависшие `uploading` в `error`.

## Кэши и согласованность

- Кэш офферов (60 с) и список кампаний (30 с) живут в памяти процесса backend и сбрасываются по TTL или явно (`refresh=true`, `refresh_offers()`). При нескольких процессах кэши не разделяются.
- Сетевые вызовы в Fetch/Upload выполняются до захвата БД-блокировок, чтобы не удерживать локи на время сети.
- Повторная проверка snapshot в Fetch и `revision` в Upload защищает от изменений concurrent-запросов.
- `force=true` — осознанный обход проверок `LOCAL_CHANGES` и `REMOTE_CHANGED`; в UI для него есть подтверждение.

## Ошибки и наблюдаемость

Все приложенческие ошибки проходят через `AppError` и превращаются в `{code, message, details?}` с нужным HTTP-статусом. Список кодов — в [API.md](API.md#коды-ошибок).

Наблюдаемость минимальная и локальная:

- `/healthz` показывает доступность БД и наличие настроек Keitaro;
- `SyncLog` хранит последние операции Fetch/Upload и ошибки;
- `last_error` потока берётся из последней ошибки в `SyncLog`;
- `docker compose logs -f backend` и `docker compose logs -f frontend` — основной источник диагностики.

## Границы решения

- Один API-ключ Keitaro и одна Basic auth-учётная запись: ролей и аудита пользователей нет.
- Нет HTTPS, reverse proxy, автоматических бэкапов и ротации секретов «из коробки».
- Нет фоновых задач: все операции синхронны и ограничены таймаутом HTTP-запроса (nginx read timeout 60 с).
- Восстановление архивных кампаний в UI не реализовано.
- Phase 0 завершён: отчёт `keitaro_contract.md` и фикстуры остаются снимком, скрипт сверки удалён.
