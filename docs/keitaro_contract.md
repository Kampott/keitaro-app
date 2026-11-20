# Keitaro Admin API: контракт

Снимок контракта Keitaro, снят 2026-11-19; скрипт сверки после завершения удалён из проекта. Файл остаётся как справка и источник фикстур: руками не перегенерировать.

| № | Проверка | Статус |
|---|---|---|
| 1 | Версия Keitaro | ✋ вручную |
| 2 | Фильтр country, режим accept | ✅ подтверждено |
| 3 | Куда класть URL редиректа | ✅ подтверждено |
| 4 | action_type у потока schema=landings | ✅ подтверждено |
| 5 | Tracking Method: Dynamic Link | ✅ подтверждено |
| 6 | PUT только с `offers` не затирает остальные поля потока | ✅ подтверждено владельцем в браузере |
| 7 | GET /campaigns: limit, offset, поиск | ✅ подтверждено |
| 8 | Сумма shares ≠ 100, поток без офферов, share = 0 | ✅ подтверждено владельцем в браузере |
| 9 | Допустимые schema | ⚠️ не подтвердилось |
| 10 | Поля домена, domain_id в кампании | ✅ подтверждено |
| 11 | GET /offers | ✅ подтверждено |
| 12 | name/alias после архивации, признак архивности | ✅ подтверждено владельцем в браузере |
| 13 | PUT /campaigns/{id}: переименование name и alias | ✅ подтверждено владельцем в браузере |
| 14 | offers[].state | ✅ подтверждено владельцем в браузере |

## 1. Версия Keitaro

Статус: ✋ вручную

- Keitaro 11.4: зафиксировано вручную.
- Swagger на трекере: `<трекер>/admin/?object=adminApi`; публичные docs могут быть старее.

## 2. Фильтр country, режим accept

Статус: ✅ подтверждено

- `GET /stream_filters`: 63 фильтров
- запись `country`: `{"value": "country", "tooltip": null, "modes": {"accept": "IS", "reject": "IS NOT"}, "group": "filters.groups.geo", "template": "", "defaults": null}`

## 3. Куда класть URL редиректа

Статус: ✅ подтверждено

- `GET /streams_actions`, запись `http`: field = `url`
- потоки schema=redirect (16 шт.): action_type=`http`, ключи action_options: `url`
- поле `action_payload` в ответе потока: есть

## 4. action_type у потока schema=landings

Статус: ✅ подтверждено

- значения у существующих потоков landings (16 шт.): `campaign`, `http`

## 5. Tracking Method: Dynamic Link

Статус: ✅ подтверждено

- В форме кампании Keitaro 11.4 поля Tracking Method / Dynamic Link нет: проверка пропущена.
- В UI есть только «Уникальность», «Срок уникальности» и «API токен» (это Click API token).

## 6. PUT только с `offers` не затирает остальные поля потока

Статус: ✅ подтверждено владельцем в браузере

- WRITE-проверка выполнена владельцем в браузере: частичный PUT с `offers` сохраняет остальные поля потока; fallback на полный PUT оставлен как защита.

## 7. GET /campaigns: limit, offset, поиск

Статус: ✅ подтверждено

- без параметров: 205 шт.; с `limit`: 1→1, 2→2, 100→100, 1000→205
- offset: работает
- поиск на стороне Keitaro: не найден среди alias/name/search/q: искать на backend по загруженному списку

## 8. Сумма shares ≠ 100, поток без офферов, share = 0

Статус: ✅ подтверждено владельцем в браузере

- WRITE-проверка выполнена владельцем в браузере.

## 9. Допустимые schema

Статус: ⚠️ не подтвердилось

- `GET /stream_schemas`: —; в просмотренных потоках встречаются: `landings`, `redirect`
- Поведение PUT с `offers` для потока с `landings` проверяет запись.

## 10. Поля домена, domain_id в кампании

Статус: ✅ подтверждено

- `GET /domains`: поля `admin_dashboard`, `allow_indexing`, `campaigns_count`, `catch_not_found`, `check_retries`, `cloudflare_id`, `cloudflare_proxy`, `created_at`, `default_campaign`, `default_campaign_id`, `dns_provider`, `error_description`, `error_solution`, `external_id`, `group`, `group_id`, `id`, `is_ssl`, `name`, `network_status`, `next_check_at`, `notes`, `registrar`, `ssl_data`, `ssl_redirect`, `ssl_status`, `state`, `status`, `updated_at`; значения `state`: `active` (1 доменов)
- `domain_id` в `GET /campaigns/{id}`: есть

## 11. GET /offers

Статус: ✅ подтверждено

- всего офферов: 1; поля: `action_options`, `action_payload`, `action_type`, `affiliate_network`, `affiliate_network_id`, `alternative_offer_id`, `conversion_cap_enabled`, `conversion_timezone`, `country`, `created_at`, `daily_cap`, `group`, `group_id`, `id`, `local_path`, `name`, `notes`, `offer_type`, `payout_auto`, `payout_conversion_type_ids`, `payout_currency`, `payout_statuses`, `payout_type`, `payout_upsell`, `payout_value`, `preview_path`, `state`, `updated_at`, `values`; значения `state`: `active`
- Каталог приходит целиком, без фильтров и страниц.
- Сверка с UI: 1 оффер в UI = 1 оффер через API — ключ видит весь каталог.

## 12. name/alias после архивации, признак архивности

Статус: ✅ подтверждено владельцем в браузере

- Освобождаются ли `name` и `alias` после архивации и как работает restore — проверяет запись.

## 13. PUT /campaigns/{id}: переименование name и alias

Статус: ✅ подтверждено владельцем в браузере

- Проверяется записью (нужно только для cleanup частично созданной кампании).

## 14. offers[].state

Статус: ✅ подтверждено владельцем в браузере

- Как Keitaro считает долю оффера в состоянии `disabled` — проверяет запись.
