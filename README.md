# Adrobot

Веб-обёртка над Keitaro Admin API: создание кампаний с двумя потоками и редактирование офферов (ТЗ v2.3).

**Состояние:** Docker Compose, backend (FastAPI + Alembic + Postgres), Basic auth, клиент Keitaro, справочники/GEO, Campaign Creator (`POST /api/campaigns`, один или несколько офферов) и локальная копия созданных кампаний работают; расчёт shares готов. Campaign Editor: чтение (`GET /api/campaigns`, `GET /api/campaigns/{id}`), выбор кампании Keitaro (`GET /api/keitaro/campaigns`, кэш 30 с, `POST /api/campaigns/fetch`), Fetch (`POST /api/campaigns/{id}/fetch`), локальные мутации офферов (Add/Delete/Restore/Fixed/PATCH) и Upload (`POST /api/flows/{flow_id}/upload`). Все мутации и Upload всегда разрешены: демо-переключателя и `FLOW_READONLY`-блокировки больше нет. В Edit Campaign можно добавить произвольный Offer ID, даже если оффера нет в каталоге. Frontend (§7) реализован: две вкладки с реальными формами, таблицей офферов, уведомлениями и подтверждениями dangerous-действий. WRITE-проверки на живом трекере ассистентом не выполнялись (Phase 0 только GET). Что сделано по пунктам ТЗ: раздел «Статус реализации» в самом ТЗ.

## Технологии

Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, psycopg 3, httpx; React + TypeScript + Vite; nginx; Docker Compose.

## Структура

```text
docker-compose.yml        db + backend + frontend (порты только на 127.0.0.1)
.env.example              шаблон настроек
backend/
  app/main.py             приложение, /healthz, подключение роутеров
  app/api/deps.py         Basic auth, клиент Keitaro
  app/api/keitaro.py      GET /api/keitaro/ping, справочники, POST /api/keitaro/groups
  app/api/campaigns.py    Creator, список/карточка, Fetch, мутации офферов
  app/api/flows.py        POST /api/flows/{id}/upload
  app/api/geo.py          GET /api/geo
  app/core/config.py      настройки из env, fail-closed проверка авторизации
  app/core/errors.py      единый формат ошибки {code, message, details?}
  app/services/keitaro_client.py   ЕДИНСТВЕННАЯ точка входа в Keitaro
  app/services/catalog_service.py  справочники и кэш /offers на 60 с
  app/services/share_calculator.py расчёт shares (MIN_SHARE = 1)
  app/services/campaign_service.py последовательность создания (ТЗ §3.5)
  app/services/sync_service.py     Fetch и запись локальной копии
  alembic/                миграции (0001 пустая, 0002 — таблицы редактора, 0003 — remote_payload потока)
  scripts/keitaro_discovery.py     Phase 0: сверка контракта Keitaro (только GET)
  tests/                  pytest; tests/fixtures/keitaro/ создаётся discovery-скриптом
  pytest.ini
docs/keitaro_contract.md  генерируется discovery-скриптом
docs/keitaro_write_api.md выжимка write-эндпоинтов из Swagger (для разработки)
docs/keitaro_openapi.yaml Swagger-спецификация Keitaro, сохранённая из Swagger UI
docs/keitaro_openapi.json её нормализованная JSON-копия
  app/services/editor_service.py   чтение/Fetch Campaign Editor
  app/services/offer_service.py    локальные мутации офферов
  app/services/upload_service.py   Upload в Keitaro
frontend/
  src/api.ts              fetch с {code, message, details?}, Basic auth в памяти
  src/App.tsx             вкладки, toasts, форма Basic auth
  src/components/         CreateCampaign.tsx, EditCampaign.tsx
  src/style.css           стили таблиц, форм, уведомлений
  nginx.conf              прокси /api и /healthz на backend
```

## Требования

Docker с Compose v2. Для запуска без Docker: Python 3.11+, Node 20+.

## Запуск через Docker Compose

```bash
cp .env.example .env
# впиши в .env KEITARO_BASE_URL (без /admin!) и KEITARO_API_KEY
docker compose up --build
```

Backend при старте сам выполняет `alembic upgrade head`. Если что-то не поднялось: `docker compose logs backend`.

## Что потыкать

| Что | Где | Что должно быть |
|---|---|---|
| Интерфейс | http://127.0.0.1:8080 | вкладка **Create Campaign**: GEO (12 строк сразу, выбранные countries в чипсах, порядок списка стабилен), offer autocomplete в одном поле с выпадающим списком (уже выбранные офферы скрыты), domain/group/source, результат с tracking URL; вкладка **Edit Campaign**: выбор кампании Keitaro одним combobox вместо пары «поиск + select», потоки (не-`landings` видны, но серые и недоступны), таблица офферов, добавление из каталога или по произвольному Offer ID в одном поле, Delete/Restore, Fixed, Local Status из данных backend, share `step=1` с сохранением по Enter/Save, сумма shares от backend, одна кнопка Fetch, Upload, Deleted Offers; после мутаций выбранный поток не сбрасывается |
| Живость | http://127.0.0.1:8080/healthz | `{"status":"ok","db":true,"keitaro_configured":true}` |
| Проверка Keitaro | http://127.0.0.1:8000/api/keitaro/ping | `{"ok":true,"campaigns_returned":N}`; `N` = 1, если в трекере есть кампании (значит `limit` работает) |
| Swagger | http://127.0.0.1:8000/docs | только при `APP_ENV=development`, в production закрыт |
| Создание кампании | `POST http://127.0.0.1:8000/api/campaigns` с Basic auth и телом `{name, geo, offer_ids, domain_id, group_id, source_id}` (`offer_id` оставлен для совместимости) | кампания + 2 потока в Keitaro, локальная копия в Postgres, ответ с ID, alias, tracking URL и списком `offers`; shares между офферами считает backend |
| Список кампаний Keitaro | `GET http://127.0.0.1:8000/api/keitaro/campaigns?search=test` | `{id,name,alias,state}` для выбора в Editor; поиск по названию/alias/ID, без `token`; ответ кэшируется на 30 с, `?refresh=true` обновляет кэш, UI фильтрует загруженный список локально |
| Выбрать кампанию в Editor | `POST http://127.0.0.1:8000/api/campaigns/fetch` с телом `{"keitaro_id": 216227}` | первый вызов создаёт локальную копию через Fetch; 409 `LOCAL_CHANGES` при локальных правках (нужен `force: true`) |
| Список локальных кампаний | `GET http://127.0.0.1:8000/api/campaigns` | массив с id/keitaro_id/name/alias и агрегированным `status` |
| Карточка кампании | `GET http://127.0.0.1:8000/api/campaigns/1` | потоки, офферы, `shares_sum` и `shares_valid` от backend, `readonly`, `last_error`, раздел `deleted_offers` |
| Fetch из Keitaro | `POST http://127.0.0.1:8000/api/campaigns/1/fetch` (при локальных правках `?force=true`) | обновлённая карточка; 409 `BUSY`/`LOCAL_CHANGES` при конфликте |
| Добавить оффер | `POST .../api/campaigns/1/flows/2/offers` с телом `{"offer_id": 40004}` | оффер из каталога, из Deleted Offers или произвольный ID (название тогда недоступно); shares пересчитаны, 409 `DUPLICATE_OFFER` для активного дубля |
| Удалить / восстановить | `DELETE .../offers/40004` / `POST .../offers/40004/restore` | мягкое удаление и возврат из Deleted Offers; новый/восстановленный оффер получает средний вес |
| Поменять share / Fixed | `PATCH .../offers/40004` с телом `{"share": 40}` или `{"is_fixed": true}` | ручной share автоматически включает Fixed (D1); снятие Fixed выравнивает доли всех незакреплённых офферов (неровный остаток детерминированно: 34/33/33 для трёх); `share` вместе с `is_fixed: false` → 422 `INVALID_REQUEST` |
| Upload потока | `POST http://127.0.0.1:8000/api/flows/2/upload` с телом `{"force": false}` | PUT offers + контрольное чтение; 409 `REMOTE_CHANGED`/`BUSY`/`CAMPAIGN_ARCHIVED`, 422 `EMPTY_FLOW`/`INVALID_SHARES` |
| БД | `psql postgresql://adrobot:adrobot@127.0.0.1:5433/adrobot -c "select * from alembic_version"` | `0003` |

### Проверка WRITE в UI

Демо-переключателя и блокировки `FLOW_READONLY` больше нет: Add/Delete/Restore, PATCH и Upload разрешены для всех потоков. Поле `readonly` остаётся в ответе backend как справочная информация, но не запрещает действия. Локальные правки и Upload в живой трекер выполняются только по вашему действию в UI. Ассистент такие WRITE-вызовы не делал; WRITE-пути покрыты только моками в тестах.

Выпадающие подсказки открываются под полем ввода и не сжимают его; кампания и оффер выбираются в одном комбинированном поле. Несохранённая доля оффера сохраняется по Enter или кнопке Save и не теряется при переходе к другому полю; остальные несохранённые доли при этом не сбрасываются. Внутренние состояния операций в уведомлениях заменены читаемыми сообщениями, дублирующий Fetch убран.

Basic auth: если в `.env` заданы `APP_BASIC_AUTH_USER` и `APP_BASIC_AUTH_PASSWORD`, браузер спросит логин при первом обращении к `/api`. `/healthz` всегда открыт. Для первого запуска можно оставить пустыми (только при `APP_ENV=development`).

### Если Keitaro отвечает ошибкой

Коды ниже приходят в уведомлениях формы; отдельного блока «Статус» в интерфейсе нет. Диагностику доступности можно сделать через `/healthz` и `/api/keitaro/ping`.

| Код | Причина |
|---|---|
| `KEITARO_NOT_CONFIGURED` | не заданы `KEITARO_BASE_URL` / `KEITARO_API_KEY` в `.env` (после правки `.env`: `docker compose up -d --force-recreate backend`) |
| `KEITARO_UNREACHABLE` | неверный адрес, нет сети или таймаут |
| `KEITARO_AUTH` | ключ неверный или у редакции Keitaro нет Admin API (402) |
| `KEITARO_BAD_RESPONSE`, «ответ не JSON» | в `KEITARO_BASE_URL` лишний `/admin` или это не адрес трекера |

## Переменные окружения

| Переменная | Обязательна | Назначение |
|---|---|---|
| `KEITARO_BASE_URL` | да | адрес трекера без `/admin` и `/admin_api/v1` |
| `KEITARO_API_KEY` | да | ключ Admin API (только backend, наружу не отдаётся) |
| `DATABASE_URL` | да | `postgresql+psycopg://user:pass@host:5432/db`; в Compose собирается автоматически |
| `APP_ENV` | нет | `production` (по умолчанию) или `development` |
| `APP_BASIC_AUTH_USER`, `APP_BASIC_AUTH_PASSWORD` | да при `production` | без них production-приложение не стартует |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | нет | для Compose, по умолчанию `adrobot` |

Остальные переменные из ТЗ §2.2 (`KEITARO_DEFAULT_*`, `GOOGLE_REDIRECT_URL`) добавятся вместе с кодом, который их использует.

## Запуск без Docker

```bash
docker compose up -d db                 # Postgres на 127.0.0.1:5433

cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
set -a; . ../.env; set +a               # подгрузить .env в окружение
alembic upgrade head
uvicorn app.main:app --reload           # http://localhost:8000

cd ../frontend                          # в другом терминале
npm install
npm run dev                             # http://localhost:5173, /api проксируется на :8000
```

Windows: проще через Docker Compose.

## Миграции

Новую миграцию создавай локально (команды выше, БД на :5433), чтобы файл попал в репозиторий, а не остался внутри контейнера:

```bash
cd backend
alembic revision --autogenerate -m "описание"   # модели импортируй в alembic/env.py
alembic upgrade head
```

## Тесты

```bash
docker compose run --rm --build backend python -m pytest -q
# или локально в venv: cd backend && python -m pytest -q
```

Сборка frontend (TypeScript + Vite, через nginx):

```bash
docker compose build frontend
# внутри образа выполняется: npm ci && npm run build (tsc --noEmit && vite build)
```

Тесты используют отдельную PostgreSQL-БД `<DATABASE_URL>_test` (по умолчанию `adrobot_test`, можно переопределить `TEST_DATABASE_URL`); SQLite не используется. Keitaro мокается (`respx`), реальный ключ не нужен; WRITE-вызовы в живой трекер тестами не выполняются. Покрыто: клиент Keitaro (нормализация ошибок, повторы только для GET), Basic auth и fail-closed старт, discovery-скрипт, модели/миграции, справочники и GEO, расчёт shares, Campaign Creator (успех, один и несколько офферов с равными целыми shares, дубли alias/name и дубли offer_id, таймаут и поиск по alias, архивация при частичной ошибке, отказ архивировать при ошибке чтения/БД, варианты tracking URL), Editor Fetch (чтение и агрегированный статус, force/BUSY, ошибки API, контроль revision, архивные офферы и потоки), Editor Offers (пересчёт shares, дубли, restore, Fixed и D1, произвольные Offer ID с подстановкой имени, мутации потоков с неактивными офферами и не-`landings` схемой, ошибки Fixed, блокировки), Editor Upload (partial/full PUT, REMOTE_CHANGED и force, ARCHIVED/BUSY/EMPTY_FLOW/INVALID_SHARES, контрольное чтение, error-log, зависшие uploading, Upload потоков с неактивными офферами), Editor Selection (список кампаний Keitaro и первый Fetch, кэш списка 30 с). Полный прогон: **147 passed**. Frontend: `docker compose build frontend` проходит (`tsc --noEmit && vite build`); в браузере проверены отсутствие блока «Статус» и демо-переключателя, автодополнение офферов на пустом поиске, несколько выбранных офферов при создании, произвольный Offer ID и активные элементы не-`landings` потока в Editor, 12 вместо 249 GEO-чекбоксов, cache hit списка кампаний (~25 мс), console errors = 0.

## Phase 0: сверка с вашим Keitaro

Скрипт `backend/scripts/keitaro_discovery.py` только читает данные (GET), в трекере ничего не создаёт и не меняет. Он проверяет по ТЗ §2.3 всё, что можно проверить чтением, сохраняет обезличенные ответы в `backend/tests/fixtures/keitaro/` и пишет отчёт `docs/keitaro_contract.md`.

```bash
# вариант 1: Docker (файлы попадут прямо в репозиторий)
docker compose run --rm --no-deps -v "${PWD}:/repo" -w /repo/backend backend python -m scripts.keitaro_discovery

# вариант 2: локально (venv из «Запуск без Docker»)
cd backend
set -a; . ../.env; set +a
python -m scripts.keitaro_discovery
```

Параметры: `--campaign-id ID` (кампания-эталон: её потоки смотрятся первыми), `--scan N` (сколько кампаний просмотреть в поисках потоков, по умолчанию 20). На Linux после запуска через Docker файлы принадлежат root: `sudo chown -R $USER: docs backend/tests/fixtures`.

Как читать `docs/keitaro_contract.md`: в начале таблица по 14 пунктам ТЗ §2.3.

| Статус | Значение |
|---|---|
| ✅ подтверждено | ответ Keitaro совпал с ожиданием ТЗ |
| 🟡 / ⏳ | нужна проверка записью (`--allow-write`, пока не реализован: он создаёт и архивирует кампании в трекере) |
| ✋ вручную | версия Keitaro и Tracking Method: смотри в админке, в отчёте есть подсказки |
| ⚠️ не подтвердилось | смотри детали пункта: чаще всего в трекере нет подходящих кампаний |

Пункты 3 и 4 (куда класть URL редиректа, `action_type` у потока с офферами) подтверждаются по существующим кампаниям. Если среди просмотренных нет потока `redirect` или `landings`, создай в UI Keitaro кампанию-эталон с такими потоками и запусти с `--campaign-id`.

**Перед коммитом фикстур.** `token` кампаний и все URL в `action_options`/`action_payload` заменяются на `REDACTED`, списки режутся до 3 элементов, но названия кампаний, офферов и доменов остаются как есть. Если репозиторий публичный, просмотри `backend/tests/fixtures/keitaro/`.

## Интеграция с Keitaro

На целевом трекере установлен **Keitaro 11.4**. Результаты Phase 0 (GET-проверки по §2.3 ТЗ, эталонная кампания 216227) — в `docs/keitaro_contract.md`; write-эндпоинты из сохранённой Swagger-спецификации разобраны в `docs/keitaro_write_api.md` (`docs/keitaro_openapi.yaml` / `.json`). WRITE-проверки на живом трекере не проводились: работает консервативный набор решений (`MIN_SHARE = 1`, partial PUT → fallback полного PUT, переименование `name`/`alias` перед архивацией). По прямому указанию владельца блокировка потоков с неактивными `offers[].state` снята: `readonly` остаётся информационным полем и не запрещает мутации и Upload.

### Особенности Keitaro API (кратко, подробности в ТЗ, Приложение A)

- Ключ в заголовке `Api-Key`, базовый путь `/admin_api/v1/`.
- Ошибки приходят по-разному: HTTP 200/400 с `{"error": ...}`, 406/422 с `{поле: [сообщения]}`, 402 означает, что Admin API нет в редакции. Клиент приводит всё к одному виду.
- `GET /offers` отдаёт весь каталог без фильтров и страниц; `GET /groups` требует `type`.
- `PUT /streams/{id}` с `offers` декларативный: пропущенные офферы удаляются. Частичный PUT на живом трекере не проверялся, поэтому после него делается контрольное чтение; если фильтры/лендинги/`action_*` затёрлись, отправляется полный `StreamRequestPut` (сохранённый `remote_payload` + свежий GET).
- `POST /campaigns` не идемпотентен, поэтому клиент не повторяет POST/PUT/DELETE автоматически.
- `GET /campaigns/{id}` в Keitaro 11.4 возвращает `domain_id` (в ТЗ v2.3 предполагалось обратное): поле в БД nullable, Fetch обновляет его из ответа, Creator сохраняет из запроса.
- `PUT /streams/{id}` принимает полный `StreamObject`; API не даёт версионирования, поэтому защита от чужих правок между чтением и записью — best-effort.

## Предупреждение

Приложение выполняет все действия в Keitaro от имени одного API-ключа. Не выставляй его наружу без `APP_ENV=production` и пароля.
