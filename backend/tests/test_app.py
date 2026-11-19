import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

AUTH = ("u", "p")


def test_production_without_credentials_does_not_start(monkeypatch):
    monkeypatch.delenv("APP_BASIC_AUTH_USER")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass


def test_api_requires_basic_auth_but_healthz_is_open():
    with TestClient(app) as c:
        r = c.get("/api/keitaro/ping")
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Basic"
        assert r.json()["code"] == "UNAUTHORIZED"
        assert c.get("/api/keitaro/ping", auth=("u", "wrong")).status_code == 401
        h = c.get("/healthz").json()
    assert h == {"status": "ok", "db": False, "keitaro_configured": True}


def test_ping_does_not_leak_keitaro_response():
    with respx.mock(base_url="https://k.example/admin_api/v1") as m:
        m.get("campaigns").respond(json=[{"id": 1, "token": "SECRET-TOKEN"}])
        with TestClient(app) as c:
            r = c.get("/api/keitaro/ping", auth=AUTH)
    assert r.json() == {"ok": True, "campaigns_returned": 1}
    assert "SECRET-TOKEN" not in r.text


def test_ping_without_keitaro_settings(monkeypatch):
    monkeypatch.setenv("KEITARO_API_KEY", "")
    get_settings.cache_clear()
    with TestClient(app) as c:
        r = c.get("/api/keitaro/ping", auth=AUTH)
    assert r.status_code == 503 and r.json()["code"] == "KEITARO_NOT_CONFIGURED"
