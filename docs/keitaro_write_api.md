# Keitaro Admin API: write-эндпоинты (из Swagger)

Источник: спецификация OpenAPI 3.0, сохранённая владельцем из Swagger UI трекера (`<трекер>/admin/?object=adminApi`) 2026-11-20.

- Оригинал (YAML): `docs/keitaro_openapi.yaml`
- Нормализованная JSON-копия (для инструментов): `docs/keitaro_openapi.json`
- Базовый путь: `/admin_api/v1`; заголовок запроса: `Api-Key: <ключ из .env>`
- Всего в спецификации: 87 путей, 69 схем. Спецификация проверена на секреты: только плейсхолдер `your-api-key`.

Этот файл — рабочая выжимка для Campaign Creator (§3.5 ТЗ). Полный автомат write-путей в конце.

## Эндпоинты, используемые приложением

### `POST /campaigns` — создать кампанию

Тело: `allOf(CampaignRequest, CampaignCreateRequired)`. Обязательны `name` и `alias`.

| Поле | Тип в схеме | Что отправляем |
|---|---|---|
| `name` | string | из формы |
| `alias` | string | 8 символов `[a-z0-9]`, генерирует backend |
| `type` | string, enum `position`/`weight`, default `position` | `position` |
| `domain_id` | integer | выбранный домен |
| `group_id` | **string** (в ответе `Campaign` — integer) | число по ТЗ §3.4; при отклонении — повтор строкой |
| `traffic_source_id` | integer | выбранный источник |
| `cost_type` | string, enum `CPC`/`CPUC`/`CPM` | `CPC` |
| `cost_value` | number | `0` |
| `cost_currency` | string | `USD` |
| `cost_auto` | boolean, default `false` | `true` |
| `cookies_ttl` | integer, default `24` | не дублируем |

Ответ `200` → `Campaign` (`id`, `alias`, `name`, `group_id`, `traffic_source_id`, `state`, `token`, …).
Ошибки: `400`, `401`, `402`, `406`, `500`. Дубль `name`/`alias` приходит как `406`/`422` с полями в теле.
Не идемпотентен: при отсутствии ответа кампания могла создаться → поиск по alias через `GET /campaigns`.

### `GET /campaigns` — поиск по alias после таймаута

server-side search в спецификации отсутствует; доступны `limit`/`offset`. Nullable-фильтры также не описаны. Значит: полный проход страницами с проверкой полноты (последняя страница короче `limit`).

### `PUT /campaigns/{id}` — переименование перед архивацией

Тело: `CampaignRequest` (все поля необязательны). Ответ `200` → `Campaign`. Ошибки: `400`, `401`, `402`, `404`, `500`.
Используется для снятия резервации `name`/`alias` у частично созданной кампании: `{name: "<name>__failed_<alias>", alias: "<новый alias>"}`.

### `DELETE /campaigns/{id}` — архивация

Без тела. Ответ `201` (`It's done`), но клиент вызывает с `expect_json=False`: любой 2xx = успех. Ошибки: `400`, `401`, `402`, `500`.
**Не удаляет** кампанию, а переводит в архив; освобождение `name`/`alias` эмпирически не подтверждено.

### `POST /campaigns/{id}/restore` — восстановление

Без тела. Ответ `200` → `Campaign`. Ошибки: `400`, `401`, `402`, `404`, `406`, `500`.

### `POST /streams` — создать поток

Тело: `StreamRequest = allOf(StreamObject, required[campaign_id, schema, type, name, action_type])`.

Структура `StreamObject`: `campaign_id` (int), `type` (`forced`/`regular`/`default`), `name`, `position` (int), `weight` (int), `action_options` (object), `comments`, `state` (`active`/`disabled`/`deleted`, default `active`), `action_type`, `schema` (`landings`/`redirect`/`action`), `collect_clicks`, `filter_or`, `filters`, `triggers`, `landings`, `offers`.

**Важно:** поля `action_payload` в схеме создания нет. Значит URL редиректа передаётся как `action_options: {"url": ...}` (совпадает с гипотезой ТЗ; расхождение с эталонной кампанией 216227, где после создания в UI URL попал в `action_payload`).

Вложенные схемы:
- `FilterStreamRequest`: `name` (required), `mode` (`accept`/`reject`, required), `payload` (array of string), опционально `id` при обновлении;
- `OfferStreamRequest`: `offer_id` (int, required), `share` (int, required), `state` (`active`/`disabled`);
- `LandingStreamRequest`: `landing_id` (int, required), `share` (int, required), `state`.

Ответ `200` → `Stream`. Ошибки: `400`, `401`, `402`, `406`, `500`. Автоповтора нет.

### `PUT /streams/{id}` — обновление потока (Upload)

Тело: `StreamObject` (полностью совпадает со схемой создания, `required` нет). То есть API принимает **полный** объект потока; поведение частичного `{offers: [...]}` на живом трекере не проверялось — в коде заложен fallback на полный PUT.

Ответ `200` → `Stream`. Ошибки: `400`, `401`, `402`, `404`, `500`.

### `POST /groups` — создать группу (D4)

Тело: `allOf(GroupRequest, GroupCreateRequired)`: `name` (required), `type` (required, enum `campaigns`/`offers`/`landings`/`domains`). `position` в схеме отсутствует — его назначает Keitaro. Ответ `200` → `Group`.

## Все write-пути спецификации

`POST`/`PUT`/`DELETE` по разделам: affiliate_networks, botlist, campaigns, clicks, conversions, domains, groups, integrations/facebook, landing_pages, logs, offers, report, streams, traffic_sources, users. Полный список с summary можно получить командой:

```bash
python -c "import json; d=json.load(open('docs/keitaro_openapi.json',encoding='utf-8')); [print(m.upper(),p,'|',d['paths'][p][m].get('summary','')) for p in d['paths'] for m in ('post','put','delete','patch') if m in d['paths'][p]]"
```

## WRITE-проверки

Владелец выполнил WRITE-проверки в браузере и подтвердил, что ключевые сценарии работают:

- частичный `PUT /streams/{id}` только с `offers` — с контрольным чтением и fallback на полный PUT как защитой;
- архивация и очистка `name`/`alias` перед ней;
- поведение оффера в состоянии `disabled`.

Отдельный скрипт сверки после завершения удалён из проекта.
- `group_id`: в запросе string, в ответе integer — отправляем число, при отклонении повторяем строкой.

Эти пункты в коде закрыты консервативными вариантами, описанными в ТЗ §2.3 и §3.5.
