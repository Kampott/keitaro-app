"""Справочники и /api/geo (ТЗ §3.2, §6)."""
import json

import respx
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.services import catalog_service
from app.services.catalog_service import CatalogService
from app.services.keitaro_client import KeitaroClient

AUTH = ("u", "p")
BASE = "https://k.example/admin_api/v1"


def test_geo_requires_auth_and_returns_iso_codes():
    with TestClient(app) as c:
        assert c.get("/api/geo").status_code == 401
        r = c.get("/api/geo", auth=AUTH)
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 200
    assert {"code": "US", "name": "United States"} in data
    assert {x["code"] for x in data} >= {"US", "MX", "AU", "RO"}
    assert all(set(x) == {"code", "name"} and len(x["code"]) == 2 for x in data)


def test_defaults_from_env():
    with TestClient(app) as c:
        r = c.get("/api/keitaro/defaults", auth=AUTH)
    assert r.status_code == 200
    assert r.json() == {
        "domain_id": 1813,
        "group_id": 10489,
        "source_id": 836,
        "google_redirect_url": "https://google.com",
    }


def test_defaults_empty_ids_and_custom_redirect(monkeypatch):
    monkeypatch.setenv("KEITARO_DEFAULT_DOMAIN_ID", "")
    monkeypatch.setenv("KEITARO_DEFAULT_GROUP_ID", "")
    monkeypatch.setenv("KEITARO_DEFAULT_TRAFFIC_SOURCE_ID", "")
    monkeypatch.setenv("GOOGLE_REDIRECT_URL", "https://example.org/")
    get_settings.cache_clear()
    with TestClient(app) as c:
        r = c.get("/api/keitaro/defaults", auth=AUTH)
    assert r.json() == {
        "domain_id": None,
        "group_id": None,
        "source_id": None,
        "google_redirect_url": "https://example.org/",
    }


def test_defaults_rejects_non_numeric_id(monkeypatch):
    monkeypatch.setenv("KEITARO_DEFAULT_GROUP_ID", "abc")
    get_settings.cache_clear()
    try:
        get_settings()
        assert False, "нечисловой ID должен быть ошибкой конфигурации"
    except RuntimeError:
        pass


def test_domains_groups_sources_return_only_id_and_name():
    with respx.mock(base_url=BASE) as m:
        m.get("domains").respond(json=[
            {"id": 1813, "name": "kylovoa.com", "is_ssl": True, "state": "active", "token": "SECRET"},
            {"id": 9999, "name": "archived.com", "is_ssl": False, "state": "deleted", "token": "SECRET"},
        ])
        m.get("groups", params={"type": "campaigns"}).respond(
            json=[{"id": 10489, "name": "Grp", "position": 1, "token": "SECRET"}]
        )
        m.get("traffic_sources").respond(json=[{"id": 836, "name": "FORTESTS", "token": "SECRET"}])
        with TestClient(app) as c:
            d = c.get("/api/keitaro/domains", auth=AUTH)
            g = c.get("/api/keitaro/groups", auth=AUTH)
            s = c.get("/api/keitaro/sources", auth=AUTH)

    assert d.json() == [{"id": 1813, "name": "kylovoa.com", "is_ssl": True}]  # архивный домен отфильтрован
    assert g.json() == [{"id": 10489, "name": "Grp"}]
    assert s.json() == [{"id": 836, "name": "FORTESTS"}]
    assert "SECRET" not in (d.text + g.text + s.text)


def _offers():
    return [
        {"id": 1, "name": "Alpha offer", "state": "active"},
        {"id": 2, "name": "Beta OFFER", "state": "active"},
        {"id": 3, "name": "Disabled alpha", "state": "disabled"},
        {"id": 4, "name": "No state"},
        {"id": 5, "name": "Gamma", "state": "active"},
    ]


def test_offers_only_active_search_by_name_and_id():
    with respx.mock(base_url=BASE) as m:
        m.get("offers").respond(json=_offers())
        with TestClient(app) as c:
            all_active = c.get("/api/keitaro/offers", auth=AUTH)
            by_name = c.get("/api/keitaro/offers", params={"search": "alpha"}, auth=AUTH)
            by_id = c.get("/api/keitaro/offers", params={"search": "2"}, auth=AUTH)

    assert [x["id"] for x in all_active.json()] == [1, 2, 5]
    assert [x["id"] for x in by_name.json()] == [1]  # disabled не попал
    assert [x["id"] for x in by_id.json()] == [2]
    assert all(set(x) == {"id", "name"} for x in all_active.json())


def test_offers_limit_is_capped_at_20():
    rows = [{"id": i, "name": f"Offer {i}", "state": "active"} for i in range(1, 41)]
    with respx.mock(base_url=BASE) as m:
        m.get("offers").respond(json=rows)
        with TestClient(app) as c:
            r = c.get("/api/keitaro/offers", params={"limit": 1000}, auth=AUTH)
            bad = c.get("/api/keitaro/offers", params={"limit": 0}, auth=AUTH)
    assert len(r.json()) == 20
    assert bad.status_code == 422


def test_offers_cached_for_60_seconds():
    with respx.mock(base_url=BASE) as m:
        route = m.get("offers").respond(json=_offers())
        with TestClient(app) as c:
            c.get("/api/keitaro/offers", auth=AUTH)
            c.get("/api/keitaro/offers", params={"search": "Beta"}, auth=AUTH)
        assert route.call_count == 1  # второй запрос не ходил в Keitaro


def test_offers_cache_ttl_expires(monkeypatch):
    svc = CatalogService(KeitaroClient("https://k.example", "KEY123"))
    with respx.mock(base_url=BASE) as m:
        route = m.get("offers").respond(json=_offers())
        svc.search_offers()
        svc.search_offers()
        assert route.call_count == 1
        monkeypatch.setattr(catalog_service, "OFFERS_TTL", 0.0)
        svc.search_offers()
        assert route.call_count == 2


def test_offers_api_failure_is_not_empty_list():
    with respx.mock(base_url=BASE) as m:
        m.get("offers").respond(500, json={"error": "boom"})
        with TestClient(app) as c:
            r = c.get("/api/keitaro/offers", auth=AUTH)
    assert r.status_code == 502
    assert r.json()["code"] == "KEITARO_BAD_RESPONSE"


def test_offers_unexpected_shape_is_error():
    with respx.mock(base_url=BASE) as m:
        m.get("offers").respond(json={"items": []})
        with TestClient(app) as c:
            r = c.get("/api/keitaro/offers", auth=AUTH)
    assert r.status_code == 502 and r.json()["code"] == "KEITARO_BAD_RESPONSE"


def test_create_group_d4():
    with respx.mock(base_url=BASE) as m:
        route = m.post("groups").respond(json={"id": 777, "name": "Новая группа"})
        with TestClient(app) as c:
            r = c.post("/api/keitaro/groups", json={"name": "  Новая группа  "}, auth=AUTH)
            bad = c.post("/api/keitaro/groups", json={"name": "   "}, auth=AUTH)
    assert r.status_code == 201
    assert r.json() == {"id": 777, "name": "Новая группа"}
    assert json.loads(route.calls.last.request.content) == {
        "name": "Новая группа",
        "type": "campaigns",
    }
    assert bad.status_code == 422
