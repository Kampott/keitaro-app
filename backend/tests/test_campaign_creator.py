"""Campaign Creator: моки Keitaro + реальная PostgreSQL."""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.db import models
from app.main import app
from app.services import campaign_service

AUTH = ("u", "p")
BASE = "https://k.example/admin_api/v1"
PAYLOAD = {
    "name": "AU promo",
    "geo": ["AU", "MX"],
    "offer_id": 18813,
    "domain_id": 1813,
    "group_id": 10489,
    "source_id": 836,
}
DOMAIN = {"id": 1813, "name": "kylovoa.com", "is_ssl": True, "state": "active"}
GROUP = {"id": 10489, "name": "Grp", "type": "campaigns"}
SOURCE = {"id": 836, "name": "FORTESTS", "state": "active"}
OFFER = {"id": 18813, "name": "Flexacil", "state": "active"}
OFFER2 = {"id": 20002, "name": "Second Offer", "state": "active"}
CAMPAIGN = {"id": 216228, "name": "AU promo", "alias": "abc123xy", "group_id": 10489, "traffic_source_id": 836}
STREAMS = [
    {"id": 1329001, "name": "GEO to Google", "schema": "redirect", "type": "regular",
     "position": 1, "state": "active", "action_type": "http", "action_options": {"url": "https://google.com"},
     "filters": [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}], "offers": []},
    {"id": 1329002, "name": "Offer", "schema": "landings", "type": "regular",
     "position": 2, "state": "active", "action_type": "http", "filters": [],
     "offers": [{"offer_id": 18813, "share": 100, "state": "active"}]},
]


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def mock_catalog(m, offers=None):
    m.get("domains").respond(json=[DOMAIN])
    m.get("groups", params={"type": "campaigns"}).respond(json=[GROUP])
    m.get("traffic_sources").respond(json=[SOURCE])
    m.get("offers").respond(json=[OFFER] if offers is None else offers)


def mock_fetch(m, *, streams=None, campaign=None):
    m.get("campaigns/216228").respond(json=campaign or CAMPAIGN)
    m.get("campaigns/216228/streams").respond(json=STREAMS if streams is None else streams)


def test_create_happy_path(client, session, monkeypatch):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        post_campaign = m.post("campaigns").respond(json=CAMPAIGN)
        post_streams = m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(200, json=STREAMS[1]),
        ])
        mock_fetch(m)
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "created"
    assert data["keitaro_id"] == 216228 and data["alias"] == "abc123xy"
    assert data["tracking_url"] == "https://kylovoa.com/abc123xy"
    assert data["geo"] == ["AU", "MX"]
    assert [(s["id"], s["schema"], s["position"]) for s in data["streams"]] == [
        (1329001, "redirect", 1), (1329002, "landings", 2),
    ]

    import json
    campaign_body = json.loads(post_campaign.calls.last.request.content)
    assert campaign_body == {
        "name": "AU promo", "alias": "abc123xy", "type": "position",
        "domain_id": 1813, "group_id": 10489, "traffic_source_id": 836,
        "cost_type": "CPC", "cost_value": 0, "cost_currency": "USD", "cost_auto": True,
    }
    f1, f2 = [json.loads(c.request.content) for c in post_streams.calls]
    assert f1["action_options"] == {"url": "https://google.com"}
    assert f1["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU", "MX"]}]
    assert f2["offers"] == [{"offer_id": 18813, "share": 100, "state": "active"}]

    row = session.scalar(select(models.Campaign).where(models.Campaign.keitaro_id == 216228))
    assert row is not None and row.domain_id == 1813
    assert [f.schema for f in row.flows] == ["redirect", "landings"]
    assert all(f.sync_status == "synced" and f.remote_hash for f in row.flows)
    assert [(o.keitaro_offer_id, o.share, o.is_fixed) for o in row.flows[1].offers] == [(18813, 100, False)]
    assert len(session.scalars(select(models.SyncLog).where(models.SyncLog.campaign_id == row.id)).all()) == 2


def test_create_multiple_offers(client, session, monkeypatch):
    import json

    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    streams = [
        STREAMS[0],
        {**STREAMS[1], "offers": [
            {"offer_id": 18813, "share": 50, "state": "active"},
            {"offer_id": 20002, "share": 50, "state": "active"},
        ]},
    ]
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m, offers=[OFFER, OFFER2])
        m.post("campaigns").respond(json=CAMPAIGN)
        post_streams = m.post("streams").mock(side_effect=[
            httpx.Response(200, json=streams[0]), httpx.Response(200, json=streams[1]),
        ])
        mock_fetch(m, streams=streams)
        r = client.post("/api/campaigns", json={**PAYLOAD, "offer_ids": [18813, 20002]}, auth=AUTH)

    assert r.status_code == 200, r.text
    data = r.json()
    assert [(o["id"], o["name"]) for o in data["offers"]] == [
        (18813, "Flexacil"), (20002, "Second Offer"),
    ]
    assert data["offer"]["id"] == 18813  # обратная совместимость
    f2 = json.loads(post_streams.calls[1].request.content)
    assert f2["offers"] == [
        {"offer_id": 18813, "share": 50, "state": "active"},
        {"offer_id": 20002, "share": 50, "state": "active"},
    ]
    row = session.scalar(select(models.Campaign).where(models.Campaign.keitaro_id == 216228))
    assert [(o.keitaro_offer_id, o.share) for o in row.flows[1].offers] == [
        (18813, 50), (20002, 50),
    ]


def test_duplicate_offer_ids_rejected(client):
    with respx.mock(base_url=BASE, assert_all_called=False):
        r = client.post(
            "/api/campaigns", json={**PAYLOAD, "offer_ids": [18813, 18813]}, auth=AUTH
        )
    assert r.status_code == 422


def test_geo_normalized_and_deduped(client, monkeypatch):
    import json

    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    bodies = []

    def capture(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=STREAMS[len(bodies) - 1])

    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.post("campaigns").respond(json=CAMPAIGN)
        m.post("streams").mock(side_effect=capture)
        mock_fetch(m)
        r = client.post("/api/campaigns", json={**PAYLOAD, "geo": ["us", "US", "mx"]}, auth=AUTH)

    assert r.status_code == 200 and r.json()["geo"] == ["US", "MX"]
    assert bodies[0]["filters"][0]["payload"] == ["US", "MX"]


def test_invalid_geo_and_empty_geo_422(client):
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        r1 = client.post("/api/campaigns", json={**PAYLOAD, "geo": ["XX"]}, auth=AUTH)
        r2 = client.post("/api/campaigns", json={**PAYLOAD, "geo": []}, auth=AUTH)
    assert r1.status_code == 422 and r2.status_code == 422


def test_unknown_reference_422(client):
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        r = client.post("/api/campaigns", json={**PAYLOAD, "offer_id": 999}, auth=AUTH)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_REFERENCE"
    assert r.json()["details"] == {"field": "offer_id", "id": 999}


def test_name_duplicate_is_not_retried(client):
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        route = m.post("campaigns").respond(406, json={"name": ["already used"]})
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)
    assert r.status_code == 422 and r.json()["code"] == "KEITARO_VALIDATION"
    assert "name" in r.json()["message"] and route.call_count == 1


def test_alias_duplicate_is_retried(client, monkeypatch):
    aliases = iter(["taken000", "free0001"])
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: next(aliases))
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        route = m.post("campaigns").mock(side_effect=[
            httpx.Response(422, json={"alias": ["already used"]}),
            httpx.Response(200, json={**CAMPAIGN, "alias": "free0001"}),
        ])
        m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(200, json=STREAMS[1]),
        ])
        mock_fetch(m)
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)
    assert r.status_code == 200 and r.json()["alias"] == "free0001"
    assert route.call_count == 2


def test_timeout_recovered_by_alias(client, monkeypatch):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.post("campaigns").mock(side_effect=httpx.ConnectError("timeout"))
        m.get("campaigns").respond(json=[CAMPAIGN])
        m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(200, json=STREAMS[1]),
        ])
        mock_fetch(m)
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)
    assert r.status_code == 200 and r.json()["keitaro_id"] == 216228


def test_timeout_without_match_is_unknown_result(client, monkeypatch):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.post("campaigns").mock(side_effect=httpx.ConnectError("timeout"))
        m.get("campaigns").respond(json=[])
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)
    assert r.status_code == 502 and r.json()["code"] == "CREATE_UNKNOWN_RESULT"
    assert r.json()["details"]["alias"] == "abc123xy"


def test_stream_failure_archives_campaign(client, monkeypatch):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.post("campaigns").respond(json=CAMPAIGN)
        m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(500, json={"error": "boom"}),
        ])
        put = m.put("campaigns/216228").respond(json=CAMPAIGN)
        delete = m.delete("campaigns/216228").respond(201, json={"ok": True})
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)

    assert r.status_code == 502 and r.json()["code"] == "CAMPAIGN_CREATE_FAILED"
    details = r.json()["details"]
    assert details["archived"] is True and details["rename_succeeded"] is True
    assert details["archived_campaign_id"] == 216228
    assert put.call_count == 1 and delete.call_count == 1


def test_structure_mismatch_archives_and_does_not_store(client, session, monkeypatch):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.post("campaigns").respond(json=CAMPAIGN)
        m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(200, json=STREAMS[1]),
        ])
        mock_fetch(m, streams=[STREAMS[0]])
        m.put("campaigns/216228").respond(json=CAMPAIGN)
        delete = m.delete("campaigns/216228").respond(201, json={"ok": True})
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)

    assert r.status_code == 502 and r.json()["code"] == "CAMPAIGN_CREATE_FAILED"
    assert delete.call_count == 1
    assert session.scalar(select(models.Campaign).where(models.Campaign.keitaro_id == 216228)) is None


def test_remote_read_failure_does_not_archive(client, monkeypatch):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.post("campaigns").respond(json=CAMPAIGN)
        m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(200, json=STREAMS[1]),
        ])
        m.get("campaigns/216228").mock(side_effect=httpx.ConnectError("network"))
        delete = m.delete("campaigns/216228").respond(201, json={"ok": True})
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)

    assert r.status_code == 200 and r.json()["local_sync_failed"] is True
    assert "Fetch" in r.json()["warning"] and delete.call_count == 0


def test_db_failure_does_not_archive(client, monkeypatch):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    from app.services import sync_service

    def boom(*args, **kwargs):
        raise sync_service.LocalStoreError("db down")

    monkeypatch.setattr(sync_service, "store_campaign", boom)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.post("campaigns").respond(json=CAMPAIGN)
        m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(200, json=STREAMS[1]),
        ])
        mock_fetch(m)
        delete = m.delete("campaigns/216228").respond(201, json={"ok": True})
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)
    assert r.status_code == 200 and r.json()["local_sync_failed"] is True
    assert delete.call_count == 0


@pytest.mark.parametrize("domain_name,expected", [
    ("http://Example.com/", "http://Example.com/abc123xy"),
    ("  kylovoa.com  ", "https://kylovoa.com/abc123xy"),
    ("*.example.com", None),
])
def test_tracking_url_variants(client, monkeypatch, domain_name, expected):
    monkeypatch.setattr(campaign_service, "_new_alias", lambda: "abc123xy")
    domain = {**DOMAIN, "name": domain_name, "is_ssl": domain_name != "http://Example.com/"}
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_catalog(m)
        m.get("domains").respond(json=[domain])
        m.post("campaigns").respond(json=CAMPAIGN)
        m.post("streams").mock(side_effect=[
            httpx.Response(200, json=STREAMS[0]), httpx.Response(200, json=STREAMS[1]),
        ])
        mock_fetch(m)
        r = client.post("/api/campaigns", json=PAYLOAD, auth=AUTH)
    assert r.status_code == 200 and r.json()["tracking_url"] == expected
