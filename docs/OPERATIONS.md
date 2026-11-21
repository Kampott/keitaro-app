# Эксплуатация

Этот гайд описывает локальную и контролируемую эксплуатацию Adrobot через Docker Compose. Приложение готово к передаче, но в Compose сознательно нет HTTPS, reverse proxy, автоматических бэкапов и ротации секретов — для общего развёртывания их нужно добавить отдельно.

## Переменные окружения

Секреты хранятся только в `.env` в корне проекта. Файл `.env` попадает в `.gitignore`; в репозитории есть только `.env.example`.

| Переменная | Обязательна | По умолчанию | Назначение |
|---|---|---|---|
| `APP_ENV` | нет | `production` | `production` или `development`. В `development` можно работать без Basic auth и доступны `/docs`, `/openapi.json` |
| `APP_BASIC_AUTH_USER` | да при `APP_ENV != development` | — | логин для всех `/api/*` |
| `APP_BASIC_AUTH_PASSWORD` | да при `APP_ENV != development` | — | пароль для всех `/api/*` |
| `KEITARO_BASE_URL` | да для работы с Keitaro | — | адрес трекера **без** `/admin` и `/admin_api/v1` |
| `KEITARO_API_KEY` | да для работы с Keitaro | — | ключ Admin API; попадает только в заголовок backend-запросов |
| `KEITARO_DEFAULT_DOMAIN_ID` | нет | `None` | домен по умолчанию в форме Create |
| `KEITARO_DEFAULT_GROUP_ID` | нет | `None` | группа по умолчанию в форме Create |
| `KEITARO_DEFAULT_TRAFFIC_SOURCE_ID` | нет | `None` | источник по умолчанию в форме Create |
| `GOOGLE_REDIRECT_URL` | нет | `https://google.com` | адрес redirect-потока при создании кампании |
| `DATABASE_URL` | да вне Compose | — | SQLAlchemy URL вида `postgresql+psycopg://user:pass@host:5432/db`. Compose собирает его сам с хостом `db` |
| `TEST_DATABASE_URL` | нет | `<DATABASE_URL>_test` | явный URL тестовой PostgreSQL-БД |
| `POSTGRES_USER` | нет | `adrobot` | пользователь БД в Compose |
| `POSTGRES_PASSWORD` | нет | `adrobot` | пароль БД в Compose; замените для любого общего развёртывания |
| `POSTGRES_DB` | нет | `adrobot` | имя основной БД |

Нечисловые значения `KEITARO_DEFAULT_*` приводят к ошибке конфигурации при старте backend. Пустое значение означает «значения по умолчанию нет».

`KEITARO_BASE_URL` — именно корень трекера, например `https://tracker.example.com`. Если указать URL с `/admin`, клиент Keitaro соберёт неверный путь и начнёт возвращать HTML вместо JSON.

## Первый запуск

Требуется Docker с Compose v2.

```bash
cp .env.example .env
# Отредактируйте .env: KEITARO_BASE_URL, KEITARO_API_KEY.
# Для реального использования задайте APP_ENV=production и пару APP_BASIC_AUTH_*.
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8080/healthz
```

Backend при старте выполняет `alembic upgrade head`. Frontend ждёт healthy backend через `depends_on`.

Адреса по умолчанию:

| Адрес | Назначение |
|---|---|
| `http://127.0.0.1:8080` | интерфейс |
| `http://127.0.0.1:8080/healthz` | health-check через nginx |
| `http://127.0.0.1:8000/api/...` | backend API |
| `http://127.0.0.1:8000/docs` | Swagger только при `APP_ENV=development` |
| `127.0.0.1:5433` | PostgreSQL с хоста (внутри Compose — порт `5432`) |

Все порты привязаны только к `127.0.0.1`. Данные PostgreSQL хранятся в именованном volume `pgdata` и не исчезают при `docker compose down`.

## Проверка здоровья

```bash
docker compose ps
curl -s http://127.0.0.1:8080/healthz
```

Ожидаемый ответ:

```json
{"status":"ok","db":true,"keitaro_configured":true}
```

Если `db=false`, проверьте контейнер `db` и `DATABASE_URL`. Если `keitaro_configured=false`, проверьте `KEITARO_BASE_URL` и `KEITARO_API_KEY` в `.env`, затем пересоздайте backend:

```bash
docker compose up -d --force-recreate backend
```

Проверку ключа без записи в трекер можно сделать через `GET /api/keitaro/ping` — она возвращает только количество кампаний, а не сырой ответ Keitaro.

## Логи и диагностика

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f db
docker compose exec backend alembic current
```

Полезные факты:

- ошибки приложения возвращаются frontend в формате `CODE: message`;
- каждая неудачная Fetch/Upload пишется в таблицу `sync_logs`;
- `last_error` потока в UI берётся из последней ошибки в `sync_logs`;
- при перезапуске backend зависшие `uploading` переводятся в `error`.

Подробнее — [диагностика](TROUBLESHOOTING.md).

## Миграции

Автоматический запуск:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
```

Ручная миграция нужна только если вы обновляете код без пересоздания контейнера или откатываетесь. Текущая ревизия — `0003 (head)`. Порядок:

- `0001` — пустая миграция;
- `0002` — таблицы `campaigns`, `campaign_flows`, `campaign_offers`, `sync_logs`;
- `0003` — колонка `campaign_flows.remote_payload JSONB`.

Не выполняйте `alembic downgrade` на рабочей БД без крайней необходимости: это удалит таблицы локальной копии, но не затронет Keitaro.

## Резервное копирование и восстановление

Команды ниже предполагают стандартные `adrobot`/`adrobot` из Compose. Для своих значений подставьте `POSTGRES_USER` и `POSTGRES_DB` из `.env`.

Создание дампа:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U adrobot -d adrobot -Fc > backups/adrobot.dump
```

Восстановление:

```bash
docker compose stop backend
docker compose exec -T db pg_restore -U adrobot -d adrobot --clean --if-exists < backups/adrobot.dump
docker compose start backend
docker compose exec backend alembic current
```

Дамп содержит только локальную копию Adrobot. Keitaro не восстанавливается из этого файла: после восстановления при необходимости сделайте Fetch в UI, чтобы сверить состояние с трекером. Храните дампы в защищённом месте: в них есть названия кампаний и офферов.

## Обновление приложения

```bash
git pull
docker compose build backend frontend
docker compose run --rm backend python -m pytest -q
docker compose up -d --force-recreate backend frontend
docker compose ps
curl -s http://127.0.0.1:8080/healthz
```

В Compose нет bind mount для исходников backend и frontend: после изменения кода нужно пересобирать образы. Миграции backend выполнит при старте сам.

Порядок безопасного обновления:

1. Сделайте бэкап PostgreSQL.
2. Обновите код и образы.
3. Прогоните тесты.
4. Пересоздайте контейнеры.
5. Проверьте `/healthz` и пару сценариев в браузере.
6. Только потом выполняйте WRITE-операции в боевом трекере, если у вас есть на это разрешение.

## Безопасность

- Храните секреты только в `.env`; не вставляйте их в README, тикеты, скриншоты и URL. `.env` уже игнорируется Git.
- Для общего развёртывания установите `APP_ENV=production`, длинный уникальный `APP_BASIC_AUTH_PASSWORD` и замените стандартный `POSTGRES_PASSWORD`.
- Не открывайте порты `8000` (backend) и `5433` (PostgreSQL) наружу. Nginx на `8080` тоже привязан к localhost.
- Для доступа вне хоста добавьте reverse proxy с TLS и собственной аутентификацией; в Compose этого нет.
- Не включайте `/docs` в production: он автоматически доступен только при `APP_ENV=development`.
- Ограничьте доступ к дампам БД и к `.env` на файловой системе (на Unix — например, `chmod 600 .env`).
- API-ключ Keitaro даёт права на campaigns/streams/offers; при подозрении на утечку ротируйте его в Keitaro и обновите `.env`.
- Учётные данные Basic auth живут в памяти вкладки и не сохраняются в localStorage/cookie.

## Чек-лист перед WRITE в Keitaro

WRITE-проверки в браузере владелец уже подтверждал. Перед новыми изменениями в боевом трекере:

1. `/healthz` показывает `db=true`, `keitaro_configured=true`.
2. В UI открываются справочники и список кампаний Keitaro.
3. Тесты backend зелёные: `153 passed`.
4. Сделан свежий дамп PostgreSQL.
5. У вас есть разрешение на изменение кампаний в целевом трекере.
6. Вы понимаете разницу между локальным изменением и отправкой в Keitaro: мутации офферов не уходят в трекер до **Upload to Keitaro**.

## Известные ограничения

- Один пользователь и один API-ключ; нет ролей, аудита действий пользователей и персональных токенов.
- Нет HTTPS и reverse proxy в поставке.
- Нет автоматических бэкапов, мониторинга и ротации секретов.
- Справочники кэшируются в памяти процесса: после изменений в Keitaro может потребоваться до 60 с или перезапуск backend.
- Список кампаний Editor кэшируется на 30 с; в API есть `refresh=true`, в UI отдельной кнопки обновления нет.
- Восстановление архивных кампаний Keitaro в интерфейсе не предусмотрено.
- Реализован консервативный набор решений: `MIN_SHARE = 1`, partial PUT с контрольным чтением и fallback на полный PUT.

Приложение можно считать shipment ready для локальной/контролируемой эксплуатации с этими оговорками. Для публичного SaaS или строго регламентированного продакшена потребуется отдельный инфраструктурный слой.
