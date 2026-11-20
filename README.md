# Adrobot

Веб-обёртка над Keitaro Admin API: создание кампаний с двумя потоками и редактирование офферов через локальный intermediate-слой.

**Статус:** готов к передаче и локальной/контролируемой эксплуатации. Backend-тесты — `147 passed`, frontend собирается без ошибок типов, UI проверен в браузере, WRITE-сценарии владелец подтвердил в браузере. Ассистент WRITE-вызовы в живой Keitaro не выполнял.

## Что приложение умеет

- Создавать кампанию в Keitaro: домен, группа, источник, GEO и один или несколько офферов; рассчитанные backend целые shares; два потока и tracking URL.
- Выбирать существующую кампанию Keitaro и создавать её локальную копию через Fetch.
- Показывать потоки: доступны для редактирования только `landings`, остальные видны, но серые и неактивные.
- Добавлять, удалять, восстанавливать офферы; редактировать share и Fixed; показывать Deleted Offers.
- Добавлять произвольный положительный Offer ID, если оффера нет в каталоге.
- Делать Fetch из Keitaro и Upload в Keitaro, включая защиту от локальных правок и чужих изменений (`force`).
- Показывать статусы, сумму shares и ошибки от backend; frontend доли не рассчитывает.
- Подтверждать опасные действия внутренним окном, а не браузерным диалогом.

Демо-режима и блокировки потоков с неактивными офферами больше нет: мутации и Upload разрешены всегда. Поле `readonly` остаётся только справочным.

## Быстрый старт

Требуется Docker с Compose v2.

```bash
cp .env.example .env
# Заполните KEITARO_BASE_URL (без /admin и /admin_api/v1) и KEITARO_API_KEY.
# Для реального использования задайте APP_ENV=production и APP_BASIC_AUTH_USER / APP_BASIC_AUTH_PASSWORD.
docker compose up --build
```

Backend при старте сам выполняет `alembic upgrade head`. Приложение будет доступно по адресам ниже.

| Адрес | Назначение |
|---|---|
| http://127.0.0.1:8080 | веб-интерфейс |
| http://127.0.0.1:8080/healthz | health-check через nginx: `{"status":"ok","db":true,"keitaro_configured":true}` |
| http://127.0.0.1:8000/api/... | backend API напрямую (Basic auth) |
| http://127.0.0.1:8000/docs | Swagger только при `APP_ENV=development` |

База PostgreSQL слушает `127.0.0.1:5433`, данные хранятся в именованном volume `pgdata`.

## Первый сценарий в UI

1. Откройте http://127.0.0.1:8080. При включённой Basic auth введите логин и пароль из `.env`.
2. Вкладка **Create Campaign**: заполните Name, GEO, Offers, Domain, Group, Source и нажмите **Create Campaign**. Результат покажет ID, alias, tracking URL, потоки и список офферов.
3. Вкладка **Edit Campaign**: выберите кампанию Keitaro. При первом выборе backend сделает Fetch и создаст локальную копию.
4. Выберите поток со схемой `landings`, измените офферы и доли, затем нажмите **Upload to Keitaro**, чтобы отправить изменения в трекер.

Подробности — в [руководстве пользователя](docs/USER_GUIDE.md).

## Команды

| Действие | Команда |
|---|---|
| Запуск/перезапуск стека | `docker compose up -d --build` |
| Остановка | `docker compose down` |
| Логи backend | `docker compose logs -f backend` |
| Статус контейнеров | `docker compose ps` |
| Тесты backend | `docker compose run --rm --build backend python -m pytest -q` |
| Сборка frontend | `docker compose build frontend` |
| Текущая миграция | `docker compose exec backend alembic current` |
| Подключение к БД | `docker compose exec db psql -U adrobot -d adrobot` |

После изменения исходников backend нужно пересобрать образ: в Compose нет bind mount для кода. Пример: `docker compose build backend`, затем `docker compose up -d --force-recreate backend`.

## Документация

- [Руководство пользователя](docs/USER_GUIDE.md) — CREATE/EDIT, офферы, shares, Fetch/Upload, подтверждения.
- [API](docs/API.md) — эндпоинты, auth, тела запросов, ошибки.
- [Архитектура](docs/ARCHITECTURE.md) — сервисы, БД, блокировки, revision, расчёт shares.
- [Эксплуатация](docs/OPERATIONS.md) — env, миграции, логи, бэкапы, обновление, безопасность.
- [Тестирование](docs/TESTING.md) — прогон, тестовая БД, покрытие, browser smoke.
- [Диагностика](docs/TROUBLESHOOTING.md) — типовые ошибки и действия.
- [Контракт Keitaro](docs/keitaro_contract.md) — снимок проверенного API-контракта.
- [WRITE-эндпоинты Keitaro](docs/keitaro_write_api.md) — заметки по записи в трекер.

## Ограничения

- Все действия в Keitaro выполняются одним API-ключом; пользователей, ролей и статистики нет.
- Порты открыты только на `127.0.0.1`. HTTPS и reverse proxy в Compose не входят: для общего развёртывания их нужно добавить отдельно.
- Секреты хранятся только в `.env`, который не должен попадать в репозиторий.
- Восстановление архивных кампаний в UI не предусмотрено.
- Частичный `PUT /streams/{id}` дополнительно проверяется контрольным чтением; при подозрении на потерю полей отправляется полный PUT.
