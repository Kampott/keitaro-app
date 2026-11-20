"""Campaign Editor, этап C: Upload в Keitaro (ТЗ §4.9)."""
import copy
import json
from datetime import datetime, timezone

import httpx
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
F1 = 1329767
NOW = datetime.now(timezone.utc).replace(tzinfo=None)

CAMPAIGN = {"id": KID, "name": "Campaign", "alias": "WVRH2s", "state": "active"}
REMOTE_STREAM = {
    "id": F1,
    "campaign_id": KID,
    "type": "regular",
    "name": "Offer flow",
    "position": 1,
    "action_type": "http",
    "action_options": {"url": "https://google.com"},
    "comments": "",
    "state": "active",
    "collect_clicks": True,
    "filter_or": False,
    "weight": 100,
    "schema": "landings",
    "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}],
    "triggers": [],
    "landings": [],
    "offers": [
        {"id": 1, "stream_id": F1, "offer_id": 18813, "share": 60, "state": "active"},
        {"id": 2, "stream_id": F1, "offer_id": 20001, "share": 40, "state": "active"},
    ],
}


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def make_campaign(session, *, status="synced", revision=5, schema="landings", offers=None):
    c = models.Campaign(
        keitaro_id=KID, name="Campaign", alias="WVRH2s",
        domain_id=1813, group_id=10489, source_id=836,
    )
    session.add(c)
    session.flush()
    f = models.CampaignFlow(
        campaign_id=c.id, keitaro_flow_id=F1, name="Offer flow", position=1,
        type="regular", schema=schema, state="active",
        sync_status=status, revision=revision,
        remote_hash=sync_service.flow_remote_hash(REMOTE_STREAM),
        remote_payload=sync_service.stream_request_payload(REMOTE_STREAM),
    )
    session.add(f)
    session.flush()
    specs = offers if offers is not None else [
        dict(koi=18813, share=60, state="active", active=True),
        dict(koi=20001, share=40, state="active", active=True),
        dict(koi=30003, share=0, state="active", active=False),
    ]
    for spec in specs:
        active = spec["active"]
        session.add(models.CampaignOffer(
            flow_id=f.id, keitaro_offer_id=spec["koi"], offer_name=str(spec["koi"]),
            share=spec["share"], keitaro_state=spec["state"],
            is_fixed=False, is_active=active,
            deleted_at=None if active else NOW,
        ))
    session.commit()
    return c, f


class Remote:
    """Имитация потока Keitaro: GET возвращает текущее состояние, PUT его меняет."""

    def __init__(self, *, campaign=None, wipe_fields=False, mismatch=False, on_put=None):
        self.campaign = campaign or dict(CAMPAIGN)
        self.stream = copy.deepcopy(REMOTE_STREAM)
        self.puts: list[dict] = []
        self.wipe_fields = wipe_fields
        self.mismatch = mismatch
        self.on_put = on_put

    def install(self, m):
        m.get(f"campaigns/{KID}").mock(side_effect=lambda _: httpx.Response(200, json=self.campaign))
        m.get(f"streams/{F1}").mock(side_effect=lambda _: httpx.Response(200, json=self.stream))
        m.put(f"streams/{F1}").mock(side_effect=self._put)

    def _put(self, request):
        body = json.loads(request.content)
        self.puts.append(body)
        if "name" in body:  # полный StreamRequestPut после fallback
            self.stream.update({k: v for k, v in body.items() if k != "offers"})
        if self.wipe_fields and len(self.puts) == 1:
            self.stream.update(filters=[], landings=[], action_options=None, action_type=None)
        self.stream["offers"] = [
            {"id": 10 + i, "stream_id": F1, "offer_id": o["offer_id"],
             "share": o["share"], "state": o["state"]}
            for i, o in enumerate(body["offers"])
        ]
        if self.mismatch:
            self.stream["offers"][0]["share"] += 1
        if self.on_put is not None:
            self.on_put()
        return httpx.Response(200, json=self.stream)


def flow_of(body):
    return next(f for f in body["flows"] if f["keitaro_flow_id"] == F1)


def test_upload_happy_path_partial_put(client, session):
    c, f = make_campaign(session)
    remote = Remote()
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 200, r.text
    assert len(remote.puts) == 1
    assert remote.puts[0] == {"offers": [
        {"offer_id": 18813, "share": 60, "state": "active"},
        {"offer_id": 20001, "share": 40, "state": "active"},
    ]}
    flow = flow_of(r.json())
    assert flow["sync_status"] == "synced" and flow["revision"] == 5
    assert flow["shares_sum"] == 100 and flow["shares_valid"] is True
    assert flow["last_uploaded_at"] is not None

    stored = session.get(models.CampaignFlow, f.id)
    assert stored.last_uploaded_at is not None
    assert stored.remote_payload["name"] == "Offer flow"
    assert stored.remote_payload["offers"] == remote.puts[0]["offers"]
    assert "id" not in stored.remote_payload and "created_at" not in stored.remote_payload
    logs = session.scalars(select(models.SyncLog).where(
        models.SyncLog.flow_id == f.id, models.SyncLog.operation == "upload"
    )).all()
    assert len(logs) == 1 and logs[0].status == "success"


def test_upload_readonly_flow_allowed(client, session):
    c, f = make_campaign(session, schema="redirect")
    remote = Remote()
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        uploaded = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert uploaded.status_code == 200, uploaded.text
    assert len(remote.puts) == 1
    assert flow_of(uploaded.json())["sync_status"] == "synced"


def test_remote_changed_requires_force(client, session):
    c, f = make_campaign(session)
    remote = Remote()
    remote.stream["name"] = "Changed in Keitaro"
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        denied = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)
        assert remote.puts == []  # до PUT дело не дошло
        allowed = client.post(f"/api/flows/{f.id}/upload", json={"force": True}, auth=AUTH)

    assert denied.status_code == 409 and denied.json()["code"] == "REMOTE_CHANGED"
    assert allowed.status_code == 200, allowed.text
    assert len(remote.puts) == 1
    assert session.get(models.CampaignFlow, f.id).sync_status == "synced"


def test_archived_campaign_rejected(client, session):
    c, f = make_campaign(session)
    remote = Remote(campaign={**CAMPAIGN, "state": "archived"})
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 409 and r.json()["code"] == "CAMPAIGN_ARCHIVED"
    assert remote.puts == []
    assert session.get(models.CampaignFlow, f.id).sync_status == "synced"


def test_missing_campaign_rejected(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        m.get(f"campaigns/{KID}").respond(404, json={"error": "not found"})
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 409 and r.json()["code"] == "CAMPAIGN_ARCHIVED"


def test_empty_flow_rejected(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, share=0, state="active", active=False),
    ])
    remote = Remote()
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "EMPTY_FLOW"
    assert remote.puts == []
    assert session.get(models.CampaignFlow, f.id).sync_status == "synced"


def test_invalid_shares_rejected(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, share=70, state="active", active=True),
        dict(koi=20001, share=20, state="active", active=True),
    ])
    remote = Remote()
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "INVALID_SHARES"
    assert remote.puts == []


def test_busy_upload_rejected(client, session):
    c, f = make_campaign(session, status="uploading")
    remote = Remote()
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 409 and r.json()["code"] == "BUSY"
    assert remote.puts == []
    assert session.get(models.CampaignFlow, f.id).sync_status == "uploading"


def test_verify_failure_marks_error_and_keeps_local_data(client, session):
    c, f = make_campaign(session)
    remote = Remote(mismatch=True)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 502 and r.json()["code"] == "KEITARO_BAD_RESPONSE"
    stored = session.get(models.CampaignFlow, f.id)
    assert stored.sync_status == "error" and stored.revision == 5
    assert stored.last_uploaded_at is None
    offers = session.scalars(select(models.CampaignOffer).where(
        models.CampaignOffer.flow_id == f.id, models.CampaignOffer.is_active.is_(True)
    )).all()
    assert sorted((o.keitaro_offer_id, o.share) for o in offers) == [(18813, 60), (20001, 40)]
    logs = session.scalars(select(models.SyncLog).where(
        models.SyncLog.flow_id == f.id, models.SyncLog.operation == "upload"
    )).all()
    assert len(logs) == 1 and logs[0].status == "error"


def test_partial_put_wiping_fields_falls_back_to_full_put(client, session):
    c, f = make_campaign(session)
    remote = Remote(wipe_fields=True)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 200, r.text
    assert len(remote.puts) == 2
    assert remote.puts[0] == {"offers": remote.puts[1]["offers"]}
    full = remote.puts[1]
    assert full["name"] == "Offer flow" and full["schema"] == "landings"
    assert full["filters"] == REMOTE_STREAM["filters"]
    assert full["action_options"] == REMOTE_STREAM["action_options"]
    assert "id" not in full and "created_at" not in full
    assert flow_of(r.json())["sync_status"] == "synced"


def test_local_mutation_during_upload_leaves_modified(client, session):
    from app.services import offer_service

    c, f = make_campaign(session)

    def mutate_during_put():
        offer_service.patch_offer(session, c.id, f.id, 20001, share=50)

    remote = Remote(on_put=mutate_during_put)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        remote.install(m)
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert flow["sync_status"] == "modified" and flow["revision"] == 6
    assert [(o["keitaro_offer_id"], o["share"]) for o in flow["offers"]] == [(18813, 50), (20001, 50)]
    # отправленный снимок не изменился: в Keitaro ушли исходные 60/40
    assert remote.puts[0]["offers"][0]["share"] == 60
    assert session.get(models.CampaignFlow, f.id).sync_status == "modified"


def test_upload_error_is_logged_with_readable_message(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        Remote().install(m)
        m.put(f"streams/{F1}").respond(422, json={"name": ["неверное имя"]})
        r = client.post(f"/api/flows/{f.id}/upload", json={}, auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "KEITARO_VALIDATION"
    log = session.scalar(select(models.SyncLog).where(
        models.SyncLog.flow_id == f.id, models.SyncLog.operation == "upload"
    ).order_by(models.SyncLog.id.desc()))
    assert log.status == "error" and "неверное имя" in log.message
    assert session.get(models.CampaignFlow, f.id).sync_status == "error"


def test_stale_upload_recovered_on_startup(session):
    c, f = make_campaign(session, status="uploading")
    from app.services.upload_service import recover_stale_uploads

    assert recover_stale_uploads(session) == 1
    assert session.get(models.CampaignFlow, f.id).sync_status == "error"
    log = session.scalar(select(models.SyncLog).where(models.SyncLog.flow_id == f.id))
    assert log.status == "error" and "Зависший" in log.message


def test_unknown_flow_404(client):
    r = client.post("/api/flows/999/upload", json={}, auth=AUTH)
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
