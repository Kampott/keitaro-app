"""Выбор кампании Editor и первый Fetch (ТЗ §4.2, §6)."""
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.db import models
from app.main import app

AUTH = ("u", "p")
BASE = "https://k.example/admin_api/v1"
KID = 216227
F1 = 1329767
F2 = 1329768

CAMPAIGN = {
    "id": KID,
    "name": "test_buslama_campaign1",
    "alias": "WVRH2s",
    "state": "active",
    "group_id": 10489,
    "traffic_source_id": 836,
    "domain_id": 1813,
    "token": "SHOULD_NOT_LEAK",
}
STREAMS = [
    {
        "id": F1, "name": "Flow 1", "position": 1, "type": "regular",
        "schema": "redirect", "state": "active", "filters": [],
        "offers": [], "action_type": "http", "action_options": {"url": "https://google.com"},
    },
    {
        "id": F2, "name": "Flow 2", "position": 2, "type": "regular",
        "schema": "landings", "state": "active", "filters": [],
        "action_type": "http", "action_options": None,
        "offers": [{"id": 1, "offer_id": 18813, "share": 100, "state": "active"}],
    },
]
OFFERS = [{"id": 18813, "name": "Flexacil", "state": "active"}]


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def install_fetch_routes(m, *, campaign=None, streams=None):
    m.get("campaigns").respond(200, json=[campaign or CAMPAIGN])
    m.get(f"campaigns/{KID}").respond(200, json=campaign or CAMPAIGN)
    m.get(f"campaigns/{KID}/streams").respond(200, json=streams if streams is not None else STREAMS)
    m.get("offers").respond(200, json=OFFERS)


def test_remote_campaigns_search_and_sanitize(client):
    rows = [
        {**CAMPAIGN, "id": 1, "name": "Alpha", "alias": "aAAA111"},
        {**CAMPAIGN, "id": 3, "name": "Gamma", "alias": "gGGG333"},
        {**CAMPAIGN, "id": 2, "name": "Beta", "alias": "bBBB222", "state": "deleted"},
    ]
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        m.get("campaigns").respond(200, json=rows)
        r = client.get("/api/keitaro/campaigns?search=beta", auth=AUTH)
        r_all = client.get("/api/keitaro/campaigns?limit=1&offset=1", auth=AUTH)

    assert r.status_code == 200
    assert r.json() == []  # удалённая кампания не попадает в список
    assert r_all.status_code == 200
    assert len(r_all.json()) == 1
    assert set(r_all.json()[0]) == {"id", "name", "alias", "state"}
    assert "token" not in r_all.json()[0]


def test_first_fetch_creates_local_copy(client, session):
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        install_fetch_routes(m)
        r = client.post("/api/campaigns/fetch", json={"keitaro_id": KID}, auth=AUTH)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["keitaro_id"] == KID and body["alias"] == "WVRH2s"
    assert len(body["flows"]) == 2
    landings = next(f for f in body["flows"] if f["schema"] == "landings")
    assert landings["shares_sum"] == 100 and landings["shares_valid"] is True
    assert landings["offers"][0]["offer_name"] == "Flexacil"

    local = session.query(models.Campaign).filter_by(keitaro_id=KID).one()
    assert local.group_id == 10489 and local.source_id == 836 and local.domain_id == 1813
    assert session.query(models.CampaignFlow).filter_by(campaign_id=local.id).count() == 2
    logs = session.query(models.SyncLog).filter_by(campaign_id=local.id, operation="fetch").all()
    assert len(logs) == 2 and all(x.status == "success" for x in logs)


def test_fetch_existing_local_checks_force(client, session):
    local = models.Campaign(
        keitaro_id=KID, name=CAMPAIGN["name"], alias=CAMPAIGN["alias"],
        domain_id=1813, group_id=10489, source_id=836,
    )
    session.add(local)
    session.flush()
    flow = models.CampaignFlow(
        campaign_id=local.id, keitaro_flow_id=F1, name="Flow 1", position=1,
        schema="redirect", sync_status="modified", revision=3,
    )
    session.add(flow)
    session.commit()

    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        install_fetch_routes(m)
        denied = client.post("/api/campaigns/fetch", json={"keitaro_id": KID}, auth=AUTH)
        allowed = client.post(
            "/api/campaigns/fetch", json={"keitaro_id": KID, "force": True}, auth=AUTH
        )

    assert denied.status_code == 409 and denied.json()["code"] == "LOCAL_CHANGES"
    assert allowed.status_code == 200, allowed.text
    assert session.query(models.Campaign).filter_by(keitaro_id=KID).count() == 1
    assert session.get(models.CampaignFlow, flow.id).sync_status == "synced"


def test_fetch_unknown_keitaro_campaign_404(client):
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        m.get("campaigns/999999").respond(404, json={"error": "not found"})
        r = client.post("/api/campaigns/fetch", json={"keitaro_id": 999999}, auth=AUTH)

    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
