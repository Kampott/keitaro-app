# API

Статический справочник по HTTP API Adrobot. Он описан по исходникам backend и не требует поднятого Swagger. В production `/docs` и `/openapi.json` отключены (`docs_url=None`, `openapi_url=None`).

## Общее

### Адреса

| Через nginx (UI) | Напрямую к backend |
|---|---|
| `http://127.0.0.1:8080/api/...` | `http://127.0.0.1:8000/api/...` |
| `http://127.0.0.1:8080/healthz` | `http://127.0.0.1:8000/healthz` |

Все адреса ниже указаны относительно `/api`, кроме `/healthz`.

### Авторизация

Все `/api/*` требуют HTTP Basic auth. Логин и пароль задаются в `.env` переменными `APP_BASIC_AUTH_USER` и `APP_BASIC_AUTH_PASSWORD`.

- При отсутствии или неверных данных — `401 UNAUTHORIZED` и заголовок `WWW-Authenticate: Basic`.
- `GET /healthz` авторизацию не требует.
- При `APP_ENV != development` backend не стартует без заполненной пары логин/пароль (fail-closed).
- При `APP_ENV=development` Basic auth можно не задавать. Такой режим предназначен только для локальной разработки.

Пример запроса:

```bash
curl -u "$APP_BASIC_AUTH_USER:$APP_BASIC_AUTH_PASSWORD" \
  http://127.0.0.1:8000/api/campaigns
```

Ни API-ключ Keitaro, ни Basic-пароль никуда в ответах не попадают.

### Формат ошибок

Ошибки приложения возвращаются в одном виде:

```json
{
  "code": "REMOTE_CHANGED",
  "message": "Поток изменился в Keitaro: сделайте Fetch или повторите Upload с force=true",
  "details": {"flow_id": 12}
}
```

`details` присутствует не всегда. Ошибки валидации Pydantic/FastAPI могут иметь стандартный вид `{"detail": [...]}`. Полный список кодов — в разделе [Коды ошибок](#коды-ошибок).

### Важные особенности

- Keitaro Admin API вызывается только с backend через `KeitaroClient`; base URL собирается как `KEITARO_BASE_URL + /admin_api/v1/`.
- GET повторяется до 3 попыток при сетевых ошибках и HTTP 5xx; POST/PUT/DELETE не повторяются.
- Справочники офферов кэшируются на 60 секунд, список кампаний Keitaro — на 30 секунд.
- В JSON потоков поле `schema` соответствует внутреннему `flow_schema`, а `type` — `flow_type`.
- Поле `readonly` в редакторе Info: мутации разрешены даже для потоков с неактивными офферами.

## Схемы ответов

### Справочники

| Объект | Поля |
|---|---|
| `Country` | `code: string`, `name: string` |
| `ReferenceItem` | `id: integer`, `name: string` |
| `DomainItem` | `id`, `name`, `is_ssl: boolean` |
| `OfferItem` | `id: integer`, `name: string` |
| `KeitaroCampaignItem` | `id`, `name`, `alias`, `state: string \| null` |
| `Defaults` | `domain_id: integer \| null`, `group_id: integer \| null`, `source_id: integer \| null`, `google_redirect_url: string` |

### CampaignSummary и CampaignDetail

`CampaignSummary`:

```json
{
  "id": 1,
  "keitaro_id": 216227,
  "name": "Campaign",
  "alias": "abc123xy",
  "status": "synced",
  "domain_id": 1813,
  "group_id": 10489,
  "source_id": 836,
  "last_fetched_at": "2026-11-20T10:00:00"
}
```

`CampaignDetail` — то же плюс `flows: FlowDetail[]`. Статус кампании — наихудший среди потоков: `error > uploading > modified > synced`.

`FlowDetail`:

```json
{
  "id": 10,
  "keitaro_flow_id": 5001,
  "name": "Offer",
  "position": 2,
  "type": "regular",
  "schema": "landings",
  "state": "active",
  "sync_status": "synced",
  "revision": 0,
  "shares_valid": true,
  "shares_sum": 100,
  "readonly": false,
  "last_error": null,
  "last_fetched_at": "2026-11-20T10:00:00",
  "last_uploaded_at": null,
  "offers": [],
  "deleted_offers": []
}
```

`OfferDetail`:

```json
{
  "id": 100,
  "keitaro_offer_id": 42,
  "offer_name": "Some offer",
  "share": 50,
  "is_fixed": false,
  "keitaro_state": "active",
  "is_active": true,
  "readonly": false,
  "name_unavailable": false
}
```

`shares_sum` и `shares_valid` всегда считает backend; frontend только отображает их.

### CampaignCreateResult

```json
{
  "status": "created",
  "keitaro_id": 216227,
  "name": "Campaign",
  "alias": "abc123xy",
  "tracking_url": "https://example.com/abc123xy",
  "domain": {"id": 1813, "name": "example.com", "is_ssl": true},
  "group": {"id": 10489, "name": "Group"},
  "source": {"id": 836, "name": "Source"},
  "offers": [{"id": 42, "name": "Some offer"}],
  "offer": {"id": 42, "name": "Some offer"},
  "geo": ["US", "GB"],
  "streams": [
    {"id": 5001, "name": "GEO to Google", "schema": "redirect", "position": 1},
    {"id": 5002, "name": "Offer", "schema": "landings", "position": 2}
  ],
  "local_sync_failed": false,
  "warning": null
}
```

`offer` дублирует первый элемент `offers` для совместимости со старыми клиентами. `status` принимает значения `created` и `created_local_sync_failed`.

## Эндпоинты

### Проверка состояния

#### `GET /healthz`

Без авторизации. Проверяет подключение к PostgreSQL и наличие настроек Keitaro.

Ответ `200`:

```json
{"status": "ok", "db": true, "keitaro_configured": true}
```

`status` всегда `ok`; смотрите флаги `db` и `keitaro_configured`. Значение `db=false` означает, что контейнер backend запущен, но БД недоступна.

### Справочники и Keitaro

#### `GET /api/geo`

Статический список стран ISO 3166-1 alpha-2. Ответ: `Country[]`.

#### `GET /api/keitaro/ping`

Проверка URL и ключа Keitaro. В ответе только счётчик:

```json
{"ok": true, "campaigns_returned": 1}
```

Сырой ответ Keitaro не отдаётся, чтобы не утекали служебные поля и `token`.

#### `GET /api/keitaro/campaigns`

Кампании Keitaro для выбора в Editor. Поиск и пагинация применяются к кэшу на 30 секунд.

| Параметр | По умолчанию | Ограничение |
|---|---|---|
| `search` | `""` | подстрока name/alias/ID, регистронезависимо |
| `limit` | `50` | `1..200` |
| `offset` | `0` | `>= 0` |
| `refresh` | `false` | `true` сбрасывает кэш перед чтением |

Ответ: `KeitaroCampaignItem[]`. Кампании в состоянии `deleted` исключены.

#### `GET /api/keitaro/defaults`

Значения по умолчанию из `.env`, без обращения к Keitaro. Ответ: `Defaults`.

#### `GET /api/keitaro/domains`

Только активные домены. Ответ: `DomainItem[]`.

#### `GET /api/keitaro/groups`

Ответ: `ReferenceItem[]`.

#### `POST /api/keitaro/groups`

Создаёт группу кампаний в Keitaro. Тело: `{"name": "Новая группа"}`. Имя не может быть пустым и длиннее 255 символов.

Ответ `201`: `ReferenceItem`.

#### `GET /api/keitaro/sources`

Ответ: `ReferenceItem[]`.

#### `GET /api/keitaro/offers`

Активные офферы из кэша (TTL 60 с).

| Параметр | По умолчанию | Примечание |
|---|---|---|
| `search` | `""` | поиск по подстроке названия или по ID |
| `limit` | `20` | сервис всё равно ограничивает результат 20 |

Ответ: `OfferItem[]`.

### Campaign Creator

#### `POST /api/campaigns`

Создаёт кампанию и два потока в Keitaro, затем сохраняет локальную копию.

Тело:

```json
{
  "name": "Campaign",
  "geo": ["US", "GB"],
  "domain_id": 1813,
  "group_id": 10489,
  "source_id": 836,
  "offer_ids": [42, 43]
}
```

| Поле | Тип | Правила |
|---|---|---|
| `name` | string | не пустое, до 255 символов |
| `geo` | string[] | не пустой список кодов ISO 3166-1 alpha-2; дубли убираются |
| `domain_id`, `group_id`, `source_id` | integer | должны существовать в справочниках |
| `offer_ids` | integer[] | 1–20 положительных уникальных ID активных офферов |
| `offer_id` | integer \| null | устаревший вариант одного оффера; если есть `offer_ids`, игнорируется для расчёта |

Ответ `200`: `CampaignCreateResult`.

Возможные ошибки: `INVALID_REFERENCE`, `KEITARO_VALIDATION`, `KEITARO_UNREACHABLE`, `KEITARO_BAD_RESPONSE`, `KEITARO_LIST_INCOMPLETE`, `CREATE_UNKNOWN_RESULT`, `AMBIGUOUS_ALIAS`, `CAMPAIGN_CREATE_FAILED`. При частичном создании кампания переименовывается и архивируется компенсационно; детали лежат в `details`.

### Campaign Editor

#### `POST /api/campaigns/fetch`

Выбирает кампанию Keitaro: если локальной копии нет, создаёт её через Fetch; если есть — выполняет обычный Fetch с проверкой локальных изменений.

Тело: `{"keitaro_id": 216227, "force": false}`. Ответ `200`: `CampaignDetail`.

Ошибки: `NOT_FOUND`, `KEITARO_NOT_FOUND`, `KEITARO_UNREACHABLE`, `KEITARO_BAD_RESPONSE`, `BUSY`, `LOCAL_CHANGES`, `LOCAL_DB_ERROR`.

#### `GET /api/campaigns`

Локальные кампании с агрегированным статусом. Ответ: `CampaignSummary[]`.

#### `GET /api/campaigns/{campaign_id}`

Карточка локальной копии: потоки, офферы, архивные офферы и статусы. Ответ: `CampaignDetail`. Ошибка: `NOT_FOUND`.

#### `POST /api/campaigns/{campaign_id}/fetch?force=false`

Перечитывает campaign из Keitaro и атомарно заменяет локальную копию. `force=true` разрешает перезапись локальных изменений. Ответ: `CampaignDetail`. Ошибки те же, что у `POST /api/campaigns/fetch`.

#### `POST /api/campaigns/{campaign_id}/flows/{flow_id}/offers`

Добавляет оффер в поток или восстанавливает его из архива. Тело: `{"offer_id": 42}`. Ответ: `CampaignDetail`.

Произвольный положительный ID принимается, даже если оффера нет в каталоге: название подставляется из ID и помечается `name_unavailable: true`.

Ошибки: `NOT_FOUND`, `DUPLICATE_OFFER` (уже активен), `KEITARO_*`.

#### `DELETE /api/campaigns/{campaign_id}/flows/{flow_id}/offers/{offer_id}`

Мягко удаляет оффер в `deleted_offers` и пересчитывает доли. Ответ: `CampaignDetail`. Ошибка: `NOT_FOUND`.

#### `POST /api/campaigns/{campaign_id}/flows/{flow_id}/offers/{offer_id}/restore`

Возвращает оффер из `deleted_offers`. Старый share и Fixed не сохраняются. Ответ: `CampaignDetail`. Ошибка: `NOT_FOUND`.

#### `PATCH /api/campaigns/{campaign_id}/flows/{flow_id}/offers/{offer_id}`

Изменяет share и/или Fixed.

Тело:

```json
{"share": 40}
```

или

```json
{"is_fixed": false}
```

| Поле | Тип | Правила |
|---|---|---|
| `share` | integer \| null | `0..100`; рабочий диапазон интерфейса — `1..100` |
| `is_fixed` | boolean \| null | включить/выключить закрепление |

Нельзя передать `share` вместе с `is_fixed: false`: сначала снимите Fixed отдельным запросом. Пустой PATCH запрещён. Ответ: `CampaignDetail`.

Ошибки: `NOT_FOUND`, `INVALID_REQUEST`, share-ошибки (`INVALID_SHARES`, `FIXED_SUM_EXCEEDS_100`, `FIXED_SUM_MUST_BE_100`, `INFEASIBLE_SHARES`).

### Upload

#### `POST /api/flows/{flow_id}/upload`

Отправляет активные офферы потока в Keitaro.

Тело необязательно:

```json
{"force": false}
```

Если тело не передано, `force = false`.

Перед отправкой backend проверяет:

1. кампания существует в Keitaro и активна (`CAMPAIGN_ARCHIVED`, `KEITARO_NOT_FOUND`);
2. поток не изменился удалённо (`REMOTE_CHANGED`, обходится `force=true`);
3. поток не отправляется сейчас (`BUSY`);
4. есть хотя бы один активный оффер (`EMPTY_FLOW`);
5. shares корректны (`INVALID_SHARES`).

Затем выполняется partial `PUT /streams/{id}` только с `offers`, контрольное чтение, при необходимости полный `PUT` с сохранённым `remote_payload`, и ещё одно контрольное чтение. При успехе обновляются `remote_hash`, `remote_payload`, `last_uploaded_at`, `sync_status` и `SyncLog`.

Ответ: `CampaignDetail`.

## Коды ошибок

| Код | HTTP | Когда возвращается |
|---|---|---|
| `UNAUTHORIZED` | 401 | нет или неверные Basic auth данные |
| `KEITARO_NOT_CONFIGURED` | 503 | не заданы `KEITARO_BASE_URL` / `KEITARO_API_KEY` |
| `NOT_FOUND` | 404 | локальная кампания, поток или оффер не найдены |
| `KEITARO_NOT_FOUND` | 404 | объект не найден в Keitaro |
| `KEITARO_AUTH` | 502 | Keitaro отклонил API-ключ или редакцию |
| `KEITARO_UNREACHABLE` | 502 | сеть, таймаут или исчерпанные повторы GET |
| `KEITARO_BAD_RESPONSE` | 502 | неожиданная форма ответа Keitaro |
| `KEITARO_VALIDATION` | 422 | Keitaro отклонил тело запроса |
| `INVALID_REFERENCE` | 422 | нет домена, группы, источника или активного оффера |
| `INVALID_REQUEST` | 422 | пустой PATCH или попытка задать share с `is_fixed=false` |
| `INVALID_SHARES` | 422 | дубль оффера, share вне диапазона, некорректные shares потока |
| `FIXED_SUM_EXCEEDS_100` | 422 | сумма закреплённых shares больше 100 |
| `FIXED_SUM_MUST_BE_100` | 422 | все офферы закреплены, но их сумма не 100 |
| `INFEASIBLE_SHARES` | 422 | не хватает долей, чтобы дать каждому свободному офферу минимум |
| `DUPLICATE_OFFER` | 409 | оффер уже активен в потоке |
| `BUSY` | 409 | поток занят Upload или Fetch |
| `LOCAL_CHANGES` | 409 | есть локальные правки, а `force=false` |
| `REMOTE_CHANGED` | 409 | поток изменился в Keitaro после последнего Fetch/Upload |
| `CAMPAIGN_ARCHIVED` | 409 | кампания в Keitaro архивирована или не найдена |
| `EMPTY_FLOW` | 422 | в потоке нет активных офферов |
| `CAMPAIGN_CREATE_FAILED` | 502 | не удалось создать поток/структуру; кампания архивирована компенсационно |
| `KEITARO_LIST_INCOMPLETE` | 502 | не удалось подтвердить полноту списка кампаний при поиске по alias |
| `CREATE_UNKNOWN_RESULT` | 502 | после обрыва ответа кампания не найдена; повторный POST не выполнялся |
| `AMBIGUOUS_ALIAS` | 502 | найдено несколько кампаний с одним alias |
| `LOCAL_DB_ERROR` | 500 | ошибка записи локальной копии при Fetch |

`FLOW_READONLY` больше не используется: демо-переключатель и блокировка удалены.
