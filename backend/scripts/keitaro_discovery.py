"""Сверка контракта Keitaro Admin API.

По умолчанию только GET; с --allow-write создаётся и архивируется тестовая кампания.

Запуск из каталога backend/:  python -m scripts.keitaro_discovery [--campaign-id ID] [--scan N] [--allow-write]
Результат: backend/tests/fixtures/keitaro/*.json и docs/keitaro_contract.md.
"""
import argparse
import json
import os
import sys
import secrets
from datetime import date
from pathlib import Path

from app.core.errors import AppError
from app.services.keitaro_client import KeitaroClient

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend/tests/fixtures/keitaro"
DOC = ROOT / "docs/keitaro_contract.md"
TRIM = 3  # списки пользовательских данных (кампании, офферы, домены…) режутся в фикстурах до стольки элементов

STATUS = {
    "ok": "✅ подтверждено",
    "part": "🟡 GET-часть сделана, остальное требует записи",
    "write": "⏳ требует записи в трекер",
    "manual": "✋ вручную",
    "check": "⚠️ не подтвердилось",
}


def redact(x, secret=False):
    """Убирает token и строки внутри action_options/action_payload (URL редиректов и офферов); ключи остаются."""
    if isinstance(x, dict):
        return {
            k: "REDACTED" if k == "token" else redact(v, secret or k in ("action_options", "action_payload"))
            for k, v in x.items()
        }
    if isinstance(x, list):
        return [redact(i, secret) for i in x]
    return "REDACTED" if secret and isinstance(x, str) and x else x


def as_list(x):
    return [i for i in x if isinstance(i, dict)] if isinstance(x, list) else []


def keys(x):
    return sorted(x) if isinstance(x, dict) else []


def uniq(values):
    return sorted({v for v in values if v is not None}, key=str)


def lst(values):
    values = list(values)
    return ", ".join(f"`{v}`" for v in values) if values else "—"

def attempt(fn):
    try:
        return fn(), ""
    except AppError as e:
        return None, f"{e.code}: {e.message}"
    except Exception:
        return None, "непредвиденная ошибка (текст скрыт)"


def first_id(items, env_name):
    raw = os.environ.get(env_name, "").strip()
    if raw:
        return int(raw)
    for it in items or []:
        if isinstance(it, dict) and it.get("id") is not None and it.get("state", "active") == "active":
            return it["id"]
    return None

def write_checks(k: KeitaroClient, save, domains, sources, offers) -> dict:
    """Контролируемые WRITE-проверки §2.3: кампания adrobot_discovery_* и архивация в конце."""
    group_raw = os.environ.get("KEITARO_DEFAULT_GROUP_ID", "").strip()
    if not group_raw:
        raise SystemExit("Для --allow-write задайте KEITARO_DEFAULT_GROUP_ID в .env")

    group_id = int(group_raw)
    domain_id = first_id(domains, "KEITARO_DEFAULT_DOMAIN_ID")
    source_id = first_id(sources, "KEITARO_DEFAULT_TRAFFIC_SOURCE_ID")
    offer = next(
        (o for o in offers or [] if o.get("state", "active") == "active" and o.get("id") is not None),
        None,
    )
    if not (domain_id and source_id and offer):
        raise SystemExit("Для write-проверок нужны домен, источник и хотя бы один активный оффер")

    offer_id = offer["id"]
    suffix = secrets.token_hex(4)
    name = f"adrobot_discovery_{suffix}"
    alias = secrets.token_hex(4)[:8]
    url = os.environ.get("GOOGLE_REDIRECT_URL", "").strip() or "https://google.com"
    result = {}

    def campaign_body(n, a):
        return {
            "name": n,
            "alias": a,
            "type": "position",
            "domain_id": domain_id,
            "group_id": group_id,
            "traffic_source_id": source_id,
            "cost_type": "CPC",
            "cost_value": 0,
            "cost_currency": "USD",
            "cost_auto": True,
        }

    c, err = attempt(lambda: k.request("POST", "campaigns", json=campaign_body(name, alias)))
    if err or not isinstance(c, dict) or c.get("id") is None:
        result["fatal"] = f"Не удалось создать кампанию: {err or 'нет id в ответе'}"
        return result

    cid = c["id"]
    save("discovery_campaign", c)

    def flow1_body():
        return {
            "campaign_id": cid,
            "name": "discovery GEO",
            "type": "regular",
            "schema": "redirect",
            "action_type": "http",
            "action_options": {"url": url},
            "position": 1,
            "state": "active",
            "collect_clicks": True,
            "filters": [{"name": "country", "mode": "accept", "payload": ["MX"]}],
        }

    def flow2_body():
        return {
            "campaign_id": cid,
            "name": "discovery offer",
            "type": "regular",
            "schema": "landings",
            "action_type": "http",
            "position": 2,
            "state": "active",
            "collect_clicks": True,
            # фильтр и action_options добавлены только для проверки п.6; кампания всё равно архивируется
            "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
            "action_options": {"url": url},
            "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        }

    f1, err1 = attempt(lambda: k.request("POST", "streams", json=flow1_body()))
    f2, err2 = attempt(lambda: k.request("POST", "streams", json=flow2_body()))

    # --- п.3: куда реально попал URL ---
    if f1 and f1.get("id"):
        raw, e3 = attempt(lambda: k.request("GET", f"streams/{f1['id']}"))
        if raw:
            save("discovery_redirect_stream", raw)
            in_opts = isinstance(raw.get("action_options"), dict) and "url" in raw["action_options"]
            in_payload = bool(raw.get("action_payload"))
            place = "action_options.url" if in_opts else "action_payload" if in_payload else "не найдено"
            result[3] = (
                "ok" if in_opts or in_payload else "check",
                [
                    f"URL после реального POST /streams: `{place}`",
                    f"ключи action_options: {lst(keys(raw.get('action_options')))}",
                    "Этот результат главнее GET-наблюдений из существующих потоков.",
                ],
            )
        else:
            result[3] = ("check", [f"GET потока не удался: {e3}"])

    # --- п.6, п.9, п.8, п.14 ---
    sid = f2.get("id") if f2 else None
    good_offers = {"offers": [{"offer_id": offer_id, "share": 100, "state": "active"}]}

    if sid:
        before, e_before = attempt(lambda: k.request("GET", f"streams/{sid}"))
        if before:
            save("discovery_landings_stream", before)
        _, e_put = attempt(lambda: k.request("PUT", f"streams/{sid}", json=good_offers))
        if e_put:
            result[6] = ("check", [f"PUT только с offers отклонён: {e_put}"])
            result[9] = ("check", [f"PUT с offers для schema=landings отклонён: {e_put}"])
        else:
            after, _ = attempt(lambda: k.request("GET", f"streams/{sid}"))
            watched = ("filters", "landings", "action_type", "action_options", "action_payload", "collect_clicks")
            changed = [f for f in watched if (before or {}).get(f) != (after or {}).get(f)]
            result[6] = (
                "ok" if not changed else "check",
                [
                    "PUT только с offers принят; GET до/после: "
                    + ("поля не изменились" if not changed else "изменились: " + lst(changed)),
                    "Лендинг в тестовом потоке не создавался (нет в runtime API); проверены filters/action_*/collect_clicks.",
                ],
            )
            result[9] = ("ok", ["PUT с offers для schema=landings принят"])

        probes = []

        def probe(label, body):
            _, e = attempt(lambda: k.request("PUT", f"streams/{sid}", json=body))
            probes.append(f"{label}: " + ("принято" if not e else f"отклонено ({e})"))
            return not e, e

        sum50_ok, _ = probe("share=50, сумма 50", {"offers": [{"offer_id": offer_id, "share": 50, "state": "active"}]})
        zero_ok, zero_err = probe("share=0", {"offers": [{"offer_id": offer_id, "share": 0, "state": "active"}]})
        empty_ok, _ = probe("offers=[]", {"offers": []})

        if not zero_ok and any(w in zero_err.lower() for w in ("sum", "100", "сумм")):
            probes.append("Внимание: отказ при share=0 может быть из-за суммы; для точного ответа нужен второй оффер.")
        min_share = 0 if zero_ok else 1
        result[8] = (
            "ok",
            [
                f"Итог: MIN_SHARE = {min_share}",
                f"сумма ≠ 100: {'принято' if sum50_ok else 'отклонено'}",
                f"пустой поток: {'принято' if empty_ok else 'отклонено'}",
                *probes,
            ],
        )

        _, e_disabled = attempt(
            lambda: k.request(
                "PUT",
                f"streams/{sid}",
                json={"offers": [{"offer_id": offer_id, "share": 100, "state": "disabled"}]},
            )
        )
        result[14] = (
            "ok",
            [
                "offers[].state=disabled: " + ("PUT принят" if not e_disabled else f"PUT отклонён ({e_disabled})"),
                "В MVP любые потоки с неактивным state всё равно остаются read-only для Upload.",
            ],
        )
        attempt(lambda: k.request("PUT", f"streams/{sid}", json=good_offers))
    else:
        result[6] = ("check", [f"Второй поток не создан: {err2 or 'нет id'}"])
        result[8] = ("check", ["Нет потока для проверки shares"])
        result[14] = ("check", ["Нет потока для проверки offers[].state"])

    # --- п.12: архивация / дубль / restore ---
    def archive(cid_):
        return attempt(lambda: k.request("DELETE", f"campaigns/{cid_}", expect_json=False))

    _, arch_err = archive(cid)
    p12 = []
    if arch_err:
        p12.append(f"Архивация не удалась: {arch_err}")
    else:
        p12.append("DELETE /campaigns/{id}: принят (кампания archived)")
        dup, dup_err = attempt(lambda: k.request("POST", "campaigns", json=campaign_body(name, alias)))
        if dup and dup.get("id"):
            p12.append("Повторное создание с теми же name/alias: УДАЛОСЬ → значения освобождаются")
            archive(dup["id"])
        else:
            p12.append(f"Повторное создание с теми же name/alias: не удалось → значения резервируются ({dup_err})")

        restored, rest_err = attempt(lambda: k.request("POST", f"campaigns/{cid}/restore", expect_json=False))
        if rest_err:
            p12.append(f"restore: отклонён ({rest_err})")
        else:
            cur, _ = attempt(lambda: k.request("GET", f"campaigns/{cid}"))
            p12.append(f"restore: принят, state={(cur or {}).get('state', '?')}")
    result[12] = ("ok" if not arch_err else "check", p12)

    # --- п.13: переименование перед финальной архивацией ---
    new_alias = secrets.token_hex(4)[:8]
    renamed_body = {"name": f"{name}__failed_{alias}", "alias": new_alias}
    _, ren_err = attempt(lambda: k.request("PUT", f"campaigns/{cid}", json=renamed_body))
    result[13] = (
        "ok" if not ren_err else "check",
        [
            "PUT /campaigns/{id} с name+alias: " + ("принят" if not ren_err else f"отклонён ({ren_err})"),
            "Именно этот вызов нужен в Creator перед архивацией частично созданной кампании.",
        ],
    )

    if not arch_err:
        archive(cid)

    if err1:
        result.setdefault("fatal", f"Flow 1 не создан: {err1}")
    if err2:
        result.setdefault("fatal", f"Flow 2 не создан: {err2}")

    return result

def run(
    k: KeitaroClient,
    fixtures: Path,
    doc: Path,
    scan: int,
    campaign_id: int | None = None,
    allow_write: bool = False,
) -> None:
    fixtures.mkdir(parents=True, exist_ok=True)
    doc.parent.mkdir(parents=True, exist_ok=True)
    points = []

    def point(n, title, status, *lines):
        flat = []
        for x in lines:
            if isinstance(x, (list, tuple)):
                flat.extend(x)
            else:
                flat.append(x)
        points.append((n, title, status, tuple(flat)))

    def save(name, data, trim=False):
        if trim and isinstance(data, list):
            data = data[:TRIM]
        text = json.dumps(redact(data), ensure_ascii=False, indent=2)
        (fixtures / f"{name}.json").write_text(text + "\n", encoding="utf-8")

    def get(path, name=None, *, params=None, trim=False):
        try:
            data = k.request("GET", path, params=params)
        except AppError as e:
            print(f"  ✗ GET {path} {params or ''}: {e.code}: {e.message}")
            return None
        print(f"  ✓ GET {path} {params or ''}")
        if name:
            save(name, data, trim)
        return data

    # --- справочники ---
    campaigns = get("campaigns", "campaigns", trim=True)
    if campaigns is None:
        sys.exit("GET /campaigns не прошёл: проверьте KEITARO_BASE_URL и ключ (ошибка выше)")
    cl = as_list(campaigns)
    actions = as_list(get("streams_actions", "streams_actions"))
    schemas = as_list(get("stream_schemas", "stream_schemas"))
    get("stream_types", "stream_types")  # справочник; в логике приложения не используется
    filters = as_list(get("stream_filters", "stream_filters"))
    domains = as_list(get("domains", "domains", trim=True))
    get("groups", "groups_campaigns", params={"type": "campaigns"}, trim=True)
    sources = as_list(get("traffic_sources", "traffic_sources", trim=True))
    offers = as_list(get("offers", "offers", trim=True))
    if offers and offers[0].get("id") is not None:
        get(f"offers/{offers[0]['id']}", "offer")

    # --- п.7: limit / offset / поиск у GET /campaigns ---
    sizes, full = {}, []
    for lim in (1, 2, 100, 1000):
        d = get("campaigns", params={"limit": lim})
        sizes[lim] = len(d) if isinstance(d, list) else "ошибка"
        if lim == 1000 and isinstance(d, list):
            full = as_list(d)
    offset_ok, search = None, []
    if len(full) >= 2:
        a = as_list(get("campaigns", params={"limit": 1, "offset": 0}))
        b = as_list(get("campaigns", params={"limit": 1, "offset": 1}))
        offset_ok = bool(a and b and a[0].get("id") != b[0].get("id"))
        c0 = full[0]
        for param, value in (("alias", c0.get("alias")), ("name", c0.get("name")), ("search", c0.get("name")), ("q", c0.get("name"))):
            res = get("campaigns", params={param: value, "limit": 1000}) if value is not None else None
            if isinstance(res, list) and 0 < len(res) < len(full):  # параметр сузил выдачу: значит, поддерживается
                search.append(param)
    point(
        7, "GET /campaigns: limit, offset, поиск",
        "ok" if len(full) >= 2 and sizes[1] == 1 and offset_ok else "check",
        f"без параметров: {len(cl)} шт.; с `limit`: " + ", ".join(f"{n}→{v}" for n, v in sizes.items()),
        "offset: " + {True: "работает", False: "не работает", None: "не определить (нужно ≥ 2 кампаний)"}[offset_ok],
        "поиск на стороне Keitaro: "
        + (lst(search) if search else "не найден среди alias/name/search/q: искать на backend по загруженному списку (ТЗ §3.5 шаг 3, §4.2)"),
    )

    # --- потоки: просматриваем до N кампаний, ищем эталонные redirect/landings ---
    ids = list(dict.fromkeys(([campaign_id] if campaign_id else []) + [c.get("id") for c in (full or cl)]))
    ids = [i for i in ids if i is not None][: scan + bool(campaign_id)]
    campaign = get(f"campaigns/{ids[0]}", "campaign") if ids else None
    streams, listed = [], False
    for cid in ids:
        s = as_list(get(f"campaigns/{cid}/streams"))
        if s and not listed:
            save("campaign_streams", s)
            listed = True
        streams += s
    redirect = [s for s in streams if s.get("schema") == "redirect"]
    landings = [s for s in streams if s.get("schema") == "landings"]
    for name, group in (("stream_redirect_example", redirect), ("stream_landings_example", landings)):
        if group:
            save(name, group[0])
    ref = (redirect or streams or [{}])[0].get("id")
    if ref is not None:
        get(f"streams/{ref}", "stream")
    w = write_checks(k, save, domains, sources, offers) if allow_write else {}
    # --- отчёт по пунктам §2.3 ---
    point(1, "Версия Keitaro", "manual",
          "Keitaro 11.4 (в ТЗ целевая — 10.x): зафиксировано вручную.",
          "Swagger на трекере: `<трекер>/admin/?object=adminApi`; публичные docs могут быть старее.")

    country = next((f for f in filters if "country" in (f.get("value"), f.get("name"))), None)
    point(2, "Фильтр country, режим accept", "ok" if country and "accept" in json.dumps(country) else "check",
          f"`GET /stream_filters`: {len(filters)} фильтров",
          "запись `country`: " + (f"`{json.dumps(country, ensure_ascii=False)}`" if country else "не найдена"))

    http = next((a for a in actions if a.get("key") == "http"), None)
    by_type = {}
    for s in redirect:
        by_type.setdefault(s.get("action_type"), set()).update(keys(s.get("action_options")))
    lines = [f"`GET /streams_actions`, запись `http`: field = `{http.get('field')}`" if http else "`GET /streams_actions`: записи `http` нет"]
    if redirect:
        lines += [f"потоки schema=redirect ({len(redirect)} шт.): action_type=`{t}`, ключи action_options: {lst(sorted(ks))}" for t, ks in by_type.items()]
        lines.append("поле `action_payload` в ответе потока: " + ("есть" if any(s.get("action_payload") for s in redirect) else "нет или пусто"))
    else:
        lines.append(f"среди {len(ids)} просмотренных кампаний нет потока schema=redirect. Создай такой поток руками в UI и запусти с `--campaign-id <id>`.")
    if 3 in w:
        point(3, "Куда класть URL редиректа", *w[3])
    else:
        point(3, "Куда класть URL редиректа", "ok" if redirect and http else "manual", *lines)

    point(4, "action_type у потока schema=landings", "ok" if landings else "manual",
          f"значения у существующих потоков landings ({len(landings)} шт.): {lst(uniq(s.get('action_type') for s in landings))}"
          if landings else f"среди {len(ids)} просмотренных кампаний нет потока schema=landings: нужна эталонная кампания (`--campaign-id`).")

    point(5, "Tracking Method: Dynamic Link", "ok",
          "В форме кампании Keitaro 11.4 поля Tracking Method / Dynamic Link нет: пункт пропущен по ТЗ §2.3 п.5.",
          "В UI есть только «Уникальность», «Срок уникальности» и «API токен» (это Click API token).")

    point(6, "PUT только с `offers` не затирает остальные поля потока",
          *w.get(6, ("write", ["Проверяется записью (`--allow-write`)."])))

    sums = [sum(o.get("share") or 0 for o in as_list(s.get("offers"))) for s in landings]
    shares = [o.get("share") for s in landings for o in as_list(s.get("offers"))]
    point(8, "Сумма shares ≠ 100, поток без офферов, share = 0",
          *w.get(8, ("write", ["Нужна проверка записью (`--allow-write`)."])))

    skeys = sorted(x for x in {s.get("key") for s in schemas} if x)
    point(
        9,
        "Допустимые schema",
        *w.get(9, (
            "part" if {"landings", "redirect", "action"} <= set(skeys) else "check",
            [
                f"`GET /stream_schemas`: {lst(skeys)}; в просмотренных потоках встречаются: {lst(uniq(s.get('schema') for s in streams))}",
                "Поведение PUT с `offers` для потока с `landings` проверяет запись.",
            ],
        )),
    )

    dk = keys(domains[0]) if domains else []
    point(10, "Поля домена, domain_id в кампании", "ok" if domains and {"name", "is_ssl", "state"} <= set(dk) else "check",
          f"`GET /domains`: поля {lst(dk)}; значения `state`: {lst(uniq(d.get('state') for d in domains))} ({len(domains)} доменов)",
          "`domain_id` в `GET /campaigns/{id}`: " + ("нет данных" if not campaign else "есть" if "domain_id" in campaign else "нет"))

    point(11, "GET /offers", "ok" if offers else "check",
          f"всего офферов: {len(offers)}; поля: {lst(keys(offers[0]) if offers else [])}; значения `state`: {lst(uniq(o.get('state') for o in offers))}",
          "Каталог приходит целиком, без фильтров и страниц.",
          "Сверка с UI: 1 оффер в UI = 1 оффер через API — ключ видит весь каталог.")

    point(12, "name/alias после архивации, признак архивности",
          *w.get(12, ("part", ["Освобождаются ли `name` и `alias` после архивации и как работает restore — проверяет запись."])))

    point(13, "PUT /campaigns/{id}: переименование name и alias",
          *w.get(13, ("write", ["Проверяется записью (нужно только для cleanup частично созданной кампании)."])))

    point(14, "offers[].state",
          *w.get(14, ("part", ["Как Keitaro считает долю оффера в состоянии `disabled` — проверяет запись."])))
    if w.get("fatal"):
        point(99, "Write-проверки", "check", w["fatal"])


    points.sort(key=lambda p: p[0])
    md = [
        "# Keitaro Admin API: контракт (Phase 0)", "",
        f"Сгенерировано `backend/scripts/keitaro_discovery.py` "
        f"({'+WRITE' if allow_write else 'GET'}), {date.today()}. "
        "Повторный запуск перезаписывает файл: руками не править.", "",
        "| § 2.3 | Пункт | Статус |", "|---|---|---|",
    ]
    md += [f"| {n} | {t} | {STATUS[s]} |" for n, t, s, _ in points]
    for n, t, s, lines in points:
        md += ["", f"## {n}. {t}", "", f"Статус: {STATUS[s]}", ""] + [f"- {x}" for x in lines]
    doc.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nОтчёт: {doc}\nФикстуры: {fixtures}")


def main():
    ap = argparse.ArgumentParser(
        description="Phase 0: сверка контракта Keitaro Admin API (GET; --allow-write включает запись)"
    )
    ap.add_argument("--campaign-id", type=int, help="эталонная кампания: её потоки просматриваются первыми")
    ap.add_argument("--scan", type=int, default=20, help="сколько кампаний просмотреть в поисках потоков (по умолчанию 20)")
    ap.add_argument(
        "--allow-write",
        action="store_true",
        help="создаёт и архивирует тестовую кампанию adrobot_discovery_* (пп. 3, 6, 8, 12–14)",
    )
    args = ap.parse_args()
    if args.allow_write:
        if input("Создать и архивировать тестовую кампанию в Keitaro? [y/N] ").strip().lower() != "y":
            sys.exit("Отменено")
    base, key = os.environ.get("KEITARO_BASE_URL", "").strip(), os.environ.get("KEITARO_API_KEY", "").strip()
    if not (base and key):
        sys.exit("Задайте KEITARO_BASE_URL и KEITARO_API_KEY (см. .env.example)")
    run(
        KeitaroClient(base, key),
        FIXTURES,
        DOC,
        args.scan,
        args.campaign_id,
        allow_write=args.allow_write,
    )


if __name__ == "__main__":
    main()
