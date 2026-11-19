# Adrobot

Веб-обёртка над Keitaro Admin API: создание кампаний с двумя потоками и редактирование офферов (ТЗ v2.3).

**Статус:** каркас и Phase 0 (GET-часть). Работает: Docker Compose, backend (FastAPI + Alembic + Postgres), Basic auth, клиент Keitaro, скрипт сверки контракта Keitaro, frontend с двумя пустыми вкладками. Бизнес-логики (создание кампаний, редактор офферов) пока нет. Что сделано по пунктам ТЗ: раздел «Статус реализации» в самом ТЗ.

## Технологии

Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, psycopg 3, httpx; React + TypeScript + Vite; nginx; Docker Compose.

## Структура

```text
docker-compose.yml        db + backend + frontend (порты только на 127.0.0.1)
.env.example              шаблон настроек
backend/
  app/main.py             приложение, /healthz, подключение роутеров
  app/api/deps.py         Basic auth, клиент Keitaro
  app/api/keitaro.py      GET /api/keitaro/ping
  app/core/config.py      настройки из env, fail-closed проверка авторизации
  app/core/errors.py      единый формат ошибки {code, message, details?}
  app/services/keitaro_client.py   ЕДИНСТВЕННАЯ точка входа в Keitaro
  alembic/                миграции (0001 пока пустая)
  scripts/keitaro_discovery.py     Phase 0: сверка контракта Keitaro (только GET)
  tests/                  pytest; tests/fixtures/keitaro/ создаётся discovery-скриптом
  pytest.ini
docs/keitaro_contract.md  генерируется discovery-скриптом
frontend/                 Vite + React, в Docker отдаётся через nginx
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
| Интерфейс | http://127.0.0.1:8080 | две вкладки-заглушки и блок «Статус»: `✓ Backend + БД`, `✓ Keitaro: ключ принят…` |
| Живость | http://127.0.0.1:8080/healthz | `{"status":"ok","db":true,"keitaro_configured":true}` |
| Проверка Keitaro | http://127.0.0.1:8000/api/keitaro/ping | `{"ok":true,"campaigns_returned":N}`; `N` = 1, если в трекере есть кампании (значит `limit` работает) |
| Swagger | http://127.0.0.1:8000/docs | только при `APP_ENV=development`, в production закрыт |
| БД | `psql postgresql://adrobot:adrobot@127.0.0.1:5433/adrobot -c "select * from alembic_version"` | `0001` |

Basic auth: если в `.env` заданы `APP_BASIC_AUTH_USER` и `APP_BASIC_AUTH_PASSWORD`, браузер спросит логин при первом обращении к `/api`. `/healthz` всегда открыт. Для первого запуска можно оставить пустыми (только при `APP_ENV=development`).

### Что значит ошибка в блоке «Статус»

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
docker compose run --rm --no-deps backend pytest
# или локально: cd backend && pytest
```

Keitaro в тестах мокается (`respx`), реальный ключ не нужен. Покрыто: клиент Keitaro (нормализация ошибок, повторы только для GET), Basic auth и fail-closed старт, discovery-скрипт (отчёт, фикстуры, отсутствие секретов в выводе).

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

## Особенности Keitaro API (кратко, подробности в ТЗ, Приложение A)

- Ключ в заголовке `Api-Key`, базовый путь `/admin_api/v1/`.
- Ошибки приходят по-разному: HTTP 200/400 с `{"error": ...}`, 406/422 с `{поле: [сообщения]}`, 402 означает, что Admin API нет в редакции. Клиент приводит всё к одному виду.
- `GET /offers` отдаёт весь каталог без фильтров и страниц; `GET /groups` требует `type`.
- `PUT /streams/{id}` с `offers` декларативный: пропущенные офферы удаляются.
- `POST /campaigns` не идемпотентен, поэтому клиент не повторяет POST/PUT/DELETE автоматически.
- Версия Keitaro и результаты проверки на вашем трекере появятся в `docs/keitaro_contract.md` после запуска скрипта.

## Предупреждение

Приложение выполняет все действия в Keitaro от имени одного API-ключа. Не выставляй его наружу без `APP_ENV=production` и пароля.
