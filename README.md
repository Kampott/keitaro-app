# Adrobot

Веб-обёртка над Keitaro Admin API: создание кампаний с двумя потоками и редактирование офферов (ТЗ v2.3).

**Статус: скелет.** Работает: Docker Compose, backend (FastAPI + Alembic + Postgres), Basic auth, клиент Keitaro и проверка ключа, frontend с двумя пустыми вкладками. Бизнес-логики пока нет (см. «Что дальше»).

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
  tests/
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

Keitaro в тестах мокается (`respx`), реальный ключ не нужен.

## Что дальше (ТЗ §13)

1. `scripts/keitaro_discovery.py` (только GET) и Phase 0: `docs/keitaro_contract.md` + фикстуры. Разделы про версию Keitaro и особенности API появятся здесь после него.
2. `share_calculator` с тестами из Приложения C.
3. Справочники, создание кампании, Fetch, редактирование, Upload.

## Предупреждение

Приложение выполняет все действия в Keitaro от имени одного API-ключа. Не выставляй его наружу без `APP_ENV=production` и пароля.
