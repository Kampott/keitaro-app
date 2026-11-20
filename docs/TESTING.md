# Тестирование

Backend-набор: **148 passed**. Тесты используют отдельную PostgreSQL-БД, Keitaro полностью мокируется, живые WRITE-вызовы не выполняются. Frontend проверяется сборкой TypeScript/Vite и вручную в браузере.

## Запуск backend-тестов

Основной вариант — через Docker Compose:

```bash
docker compose run --rm --build backend python -m pytest -q
```

Ожидаемый итог:

```text
148 passed, 1 warning in 2.78s
```

Warning — `StarletteDeprecationWarning` от связки FastAPI TestClient/httpx; на результат не влияет.

Локальный запуск без Compose:

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate      # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
```

Для локального запуска нужна доступная PostgreSQL и `DATABASE_URL` (или `TEST_DATABASE_URL`) в окружении/`.env`. Конфигурация pytest лежит в `backend/pytest.ini`: `pythonpath = .`, `testpaths = tests`.

## Тестовая база

SQLite не используется. Тесты работают только с PostgreSQL.

- По умолчанию имя БД берётся из `DATABASE_URL` и получает суффикс `_test`: при `DATABASE_URL=.../adrobot` используется `.../adrobot_test`.
- Имя можно задать явно через `TEST_DATABASE_URL`.
- Если БД не существует, фикстура `pg_engine` создаёт её от имени того же пользователя.
- В начале сессии выполняется `Base.metadata.drop_all` и `create_all`; в конце — снова `drop_all`.
- Каждый тест идёт в отдельной транзакции с SAVEPOINT и откатывается в конце. Неожиданный `IntegrityError` внутри теста не ломает внешнюю транзакцию.
- `DATABASE_URL` в тестовом окружении по умолчанию заведомо недоступен (`127.0.0.1:1`), чтобы поймать случайный обход тестовой сессии.

Не указывайте в `TEST_DATABASE_URL` основную рабочую БД `adrobot`: тесты удаляют и пересоздают таблицы.

## Состав набора

| Файл | Тестов | Что проверяет |
|---|---:|---|
| `test_app.py` | 4 | fail-closed старт без Basic auth в production, auth на `/api/*`, открытый `/healthz`, `/api/keitaro/ping` без утечки ответа Keitaro |
| `test_keitaro_client.py` | 13 | нормализация кодов Keitaro, читаемые field-ошибки, заголовок `Api-Key`, повторы только GET, сетевые ошибки и не-JSON |
| `test_catalog.py` | 12 | `/api/geo`, defaults, справочники только с `{id,name}`, поиск офферов, кэш 60 с, ошибки Keitaro, создание группы |
| `test_share_calculator.py` | 45 | все векторы Приложения C при `MIN_SHARE=0` и `1`, приоритет явного аргумента, пустой список, детерминированные остатки, property-тесты |
| `test_models.py` | 7 | таблицы, UNIQUE/CHECK/FK, мягкое удаление, каскады, `SyncLog` — всё на PostgreSQL |
| `test_campaign_creator.py` | 17 | POST-тела для одного и нескольких офферов, GEO, дубли, таймаут и поиск по alias, компенсационная архивация, отказ архивировать при сетевой ошибке БД, tracking URL |
| `test_editor_fetch.py` | 9 | чтение и статусы, force/BUSY, ошибки Keitaro, контроль revision, архивные офферы и потоки |
| `test_editor_offers.py` | 22 | Add/Delete/Restore/Fixed/PATCH, выравнивание shares после удаления, произвольные Offer ID, `name_unavailable`, мутации «read-only» потоков, ошибки Fixed и блокировки |
| `test_editor_selection.py` | 5 | список кампаний Keitaro, лимит 1000 на 205 кампаний, локальный поиск, первый Fetch, кэш 30 с |
| `test_editor_upload.py` | 14 | partial/full PUT, `REMOTE_CHANGED` и force, `CAMPAIGN_ARCHIVED`, `BUSY`, пустой список офферов, `INVALID_SHARES`, контрольное чтение, error-log, recovery зависших `uploading` |
| **Итого** | **148** | — |

## Shares и `MIN_SHARE`

Рабочее значение константы в `share_calculator.py` — `MIN_SHARE = 1`. Тесты параметризованы и для `MIN_SHARE = 0`, чтобы сохранить все контрольные векторы расчёта и проверить обе ветки.

Проверяются:

- сумма долей всегда 100 или приложение вернуло ошибку;
- целые числа, без float/Decimal;
- детерминированное распределение остатка;
- Fixed и «опорная» доля после ручного ввода;
- `34/33/33 → 50/50` после удаления при `MIN_SHARE = 0` и `1`;
- сохранение Fixed при удалении;
- ошибки `INVALID_SHARES`, `FIXED_SUM_EXCEEDS_100`, `FIXED_SUM_MUST_BE_100`, `INFEASIBLE_SHARES`.

## Моки Keitaro и фикстуры

Во всех сетевых тестах используется `respx`: реальный Keitaro не вызывается. Тестовое окружение задаёт поддельные `KEITARO_BASE_URL=https://k.example/` и `KEITARO_API_KEY=KEY123`, поэтому настоящий ключ в тестах не нужен.

В `backend/tests/fixtures/keitaro/` лежит обезличенный снимок ответов Keitaro, снятый во время завершённой сверки контракта. Он используется как справочный материал и источник тестовых данных. Скрипт `keitaro_discovery.py` после завершения Phase 0 удалён из проекта; фикстуры не перегенерируются.

Важно: тесты никогда не вызывают POST/PUT/DELETE в живой трекер. WRITE-сценарии в браузере проверял владелец.

## Frontend

Отдельного unit-тест-раннера в проекте нет. Frontend проверяется так:

```bash
docker compose build frontend
```

Dockerfile выполняет `npm run build`, то есть `tsc --noEmit && vite build`. Успешная сборка означает отсутствие ошибок типов. Затем nginx отдаёт готовый bundle на `http://127.0.0.1:8080`.

### Браузерный smoke-чеклист

1. Откройте `http://127.0.0.1:8080`; при включённой Basic auth войдите.
2. Проверьте `http://127.0.0.1:8080/healthz`.
3. **Create Campaign**: загрузились справочники, GEO показывает до 12 строк, подсказки офферов открываются под полем, можно выбрать несколько офферов и произвольный ID в Editor.
4. **Edit Campaign**: выберите кампанию, выполнится первый Fetch, появятся потоки и таблица офферов.
5. Измените Share, проверьте `Сумма shares (от backend)` и работают Enter/Save, Fixed, Delete/Restore.
6. Проверьте внутренние окна подтверждения для Delete, Fetch при локальных изменениях и Force upload; браузерный `window.confirm` не используется.
7. Проверьте консоль разработчика в браузере: ошибок быть не должно.

WRITE-проверки в живом Keitaro выполняются только с разрешения владельца. После успешной проверки владельцем приложение считается shipment ready для локальной/контролируемой эксплуатации.

## Что делать при падении тестов

- `createdb` / `permission denied` — проверьте права `POSTGRES_USER` и доступность `127.0.0.1:5433` или хоста `db` внутри Compose.
- Падение тестов моделей — убедитесь, что используется PostgreSQL, а не SQLite.
- Ошибки Keitaro-тестов — проверьте, что `respx` перехватывает запросы и что тесты не уходят в сеть.
- Много неожиданных `KEITARO_*` — проверьте, что `.env` не подменяет тестовые переменные; `conftest.py` выставляет их через `monkeypatch`.
- Падение после изменений shares — сверьте `MIN_SHARE` и ожидаемые векторы в `test_share_calculator.py`.
