"""Campaign Editor: чтение и Fetch."""
from datetime import datetime, timezone

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.db import models
from app.main import app
from app.services import sync_service

AUTH = ("u", "p")
BASE = "https://k.example/admin_api/v1"
KID = 216227
F1, F2 = 1329767, 1329768
NOW = datetime.now(timezone.utc).replace(tzinfo=None)

REMOTE_CAMPAIGN = {
    "id": KID, "name": "Renamed", "alias": "WVRH2s",
    "group_id": 10489, "traffic_source_id": 836, "domain_id": 1813,
}
OFFERS = [
    {"id": 18813, "name": "Flexacil", "state": "active"},
    {"id": 20001, "name": "New Offer", "state": "active"},
]
STREAMS = [
    {
        "id": F1, "name": "GEO to Google", "type": "regular", "schema": "redirect",
        "position": 1, "state": "active", "action_type": "http",
        "action_options": {"url": "https://google.com"},
        "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}], "offers": [],
    },
    {
        "id": F2, "name": "Offer", "type": "regular", "schema": "landings",
        "position": 2, "state": "active", "action_type": "http",
        "filters": [], "offers": [
            {"offer_id": 18813, "share": 70, "state": "active"},
            {"offer_id": 20001, "share": 30, "state": "active"},
        ],
    },
]


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def make_campaign(session, *, status="synced", revision=1):
    c = models.Campaign(
        keitaro_id=KID, name="Original", alias="WVRH2s",
        domain_id=1111, group_id=10489, source_id=836,
    )
    session.add(c)
    session.flush()
    f1 = models.CampaignFlow(
        campaign_id=c.id, keitaro_flow_id=F1, name="Flow 1", position=1,
        type="regular", schema="redirect", state="active",
        sync_status=status, revision=revision, remote_hash="old_f1",
    )
    f2 = models.CampaignFlow(
        campaign_id=c.id, keitaro_flow_id=F2, name="Flow 2", position=2,
        type="regular", schema="landings", state="active",
        sync_status=status, revision=revision, remote_hash="old_f2",
    )
    session.add_all([f1, f2])
    session.flush()
    session.add_all([
        models.CampaignOffer(
            flow_id=f2.id, keitaro_offer_id=18813, offer_name="Flexacil",
            share=100, is_fixed=True, is_active=True,
        ),
        models.CampaignOffer(
            flow_id=f2.id, keitaro_offer_id=19999, offer_name="Removed locally",
            share=0, is_active=False, deleted_at=NOW,
        ),
    ])
    session.commit()
    return c


def mock_remote(m, *, campaign=None, streams=None, offers=None):
    m.get(f"campaigns/{KID}").respond(json=campaign or REMOTE_CAMPAIGN)
    m.get(f"campaigns/{KID}/streams").respond(json=STREAMS if streams is None else streams)
    m.get("offers").respond(json=OFFERS if offers is None else offers)


def test_fetch_happy_path(client, session):
    c = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_remote(m)
        r = client.post(f"/api/campaigns/{c.id}/fetch", auth=AUTH)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Renamed" and data["domain_id"] == 1813
    assert data["status"] == "synced" and len(data["flows"]) == 2
    assert [(f["schema"], f["position"], f["sync_status"], f["revision"]) for f in data["flows"]] == [
        ("redirect", 1, "synced", 0), ("landings", 2, "synced", 0),
    ]
    flow2 = data["flows"][1]
    assert flow2["shares_valid"] is True and flow2["readonly"] is False
    assert [(o["keitaro_offer_id"], o["share"], o["is_fixed"], o["offer_name"]) for o in flow2["offers"]] == [
        (18813, 70, True, "Flexacil"), (20001, 30, False, "New Offer"),
    ]
    assert [o["keitaro_offer_id"] for o in flow2["deleted_offers"]] == [19999]
    assert data["flows"][0]["shares_valid"] is False  # в redirect-потоке нет офферов

    assert all(f.remote_hash not in ("old_f1", "old_f2") for f in session.get(models.Campaign, c.id).flows)
    rows = session.scalars(select(models.SyncLog).where(
        models.SyncLog.campaign_id == c.id, models.SyncLog.operation == "fetch"
    )).all()
    assert len(rows) == 2 and all(x.status == "success" for x in rows)


def test_list_and_detail_status_error_and_deleted_offer(client, session):
    c = make_campaign(session, status="error")
    flows = session.scalars(select(models.CampaignFlow).order_by(models.CampaignFlow.id)).all()
    session.add(models.SyncLog(
        campaign_id=c.id, flow_id=flows[0].id, operation="upload",
        status="error", message="PUT not accepted",
    ))
    flows[1].state = "deleted"
    session.commit()

    listing = client.get("/api/campaigns", auth=AUTH)
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert listing.json()[0]["status"] == "error"

    detail = client.get(f"/api/campaigns/{c.id}", auth=AUTH)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert len(body["flows"]) == 1 and body["flows"][0]["keitaro_flow_id"] == F1
    assert body["flows"][0]["last_error"] == "PUT not accepted"
    assert body["flows"][0]["readonly"] is True  # schema=redirect
    assert [o["keitaro_offer_id"] for o in body["flows"][0]["deleted_offers"]] == []


def test_fetch_requires_force_for_local_changes(client, session):
    c = make_campaign(session, status="modified")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_remote(m)
        denied = client.post(f"/api/campaigns/{c.id}/fetch", auth=AUTH)
        assert all(route.call_count == 0 for route in m.routes)
        allowed = client.post(f"/api/campaigns/{c.id}/fetch?force=true", auth=AUTH)

    assert denied.status_code == 409 and denied.json()["code"] == "LOCAL_CHANGES"
    assert len(denied.json()["details"]["flows"]) >= 1
    assert allowed.status_code == 200 and allowed.json()["status"] == "synced"


def test_fetch_busy_conflict(client, session):
    c = make_campaign(session, status="uploading")
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_remote(m)
        r = client.post(f"/api/campaigns/{c.id}/fetch?force=true", auth=AUTH)
        assert all(route.call_count == 0 for route in m.routes)

    assert r.status_code == 409 and r.json()["code"] == "BUSY"


def test_fetch_api_error_keeps_local_data(client, session):
    c = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_remote(m)
        m.get(f"campaigns/{KID}/streams").respond(500, json={"error": "boom"})
        r = client.post(f"/api/campaigns/{c.id}/fetch", auth=AUTH)

    assert r.status_code == 502 and r.json()["code"] == "KEITARO_BAD_RESPONSE"
    fresh = session.get(models.Campaign, c.id)
    assert fresh.name == "Original" and fresh.domain_id == 1111
    assert all(f.revision == 1 and f.sync_status == "synced" for f in fresh.flows)
    error_logs = session.scalars(select(models.SyncLog).where(
        models.SyncLog.campaign_id == c.id, models.SyncLog.status == "error"
    )).all()
    assert len(error_logs) == 1 and error_logs[0].operation == "fetch"


def test_fetch_detects_revision_change_during_request(client, session, monkeypatch):
    c = make_campaign(session, status="synced")
    flow_id = session.scalars(select(models.CampaignFlow.id).limit(1)).one()

    def fake_fetch(client_, keitaro_id):
        flow = session.get(models.CampaignFlow, flow_id)
        flow.revision += 1
        flow.sync_status = "modified"
        session.flush()
        return REMOTE_CAMPAIGN, STREAMS

    monkeypatch.setattr(sync_service, "fetch_remote", fake_fetch)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        m.get("offers").respond(json=OFFERS)
        r = client.post(f"/api/campaigns/{c.id}/fetch?force=true", auth=AUTH)

    assert r.status_code == 409 and r.json()["code"] == "LOCAL_CHANGES"
    assert session.get(models.Campaign, c.id).name == "Original"


def test_fetch_marks_missing_flow_deleted(client, session):
    c = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_remote(m, streams=[STREAMS[0]])
        r = client.post(f"/api/campaigns/{c.id}/fetch", auth=AUTH)

    assert r.status_code == 200, r.text
    assert [f["keitaro_flow_id"] for f in r.json()["flows"]] == [F1]
    flows = session.scalars(select(models.CampaignFlow).order_by(models.CampaignFlow.id)).all()
    assert [(f.keitaro_flow_id, f.state) for f in flows] == [(F1, "active"), (F2, "deleted")]


def test_fetch_disabled_offer_makes_flow_readonly(client, session):
    c = make_campaign(session)
    streams = [
        STREAMS[0],
        {**STREAMS[1], "offers": [
            {"offer_id": 18813, "share": 100, "state": "active"},
            {"offer_id": 20001, "share": 0, "state": "disabled"},
        ]},
    ]
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_remote(m, streams=streams)
        r = client.post(f"/api/campaigns/{c.id}/fetch", auth=AUTH)

    assert r.status_code == 200, r.text
    flow = r.json()["flows"][1]
    assert flow["readonly"] is True
    assert all(o["readonly"] for o in flow["offers"])
    assert flow["shares_valid"] is True  # долю disabled-оффера не считаем


def test_unknown_local_campaign_404(client):
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        a = client.get("/api/campaigns/999", auth=AUTH)
        b = client.post("/api/campaigns/999/fetch", auth=AUTH)
        assert all(route.call_count == 0 for route in m.routes)

    assert a.status_code == 404 and b.status_code == 404
    assert a.json()["code"] == b.json()["code"] == "NOT_FOUND"
