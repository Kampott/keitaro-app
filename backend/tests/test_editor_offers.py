"""Campaign Editor: локальные мутации офферов."""
from datetime import datetime, timezone

import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.deps import get_db
from app.db import models
from app.main import app
import app.services.share_calculator as sc

AUTH = ("u", "p")
BASE = "https://k.example/admin_api/v1"
KID = 216227
F1 = 1329767
NOW = datetime.now(timezone.utc).replace(tzinfo=None)

OFFERS = [
    {"id": 18813, "name": "Flexacil", "state": "active"},
    {"id": 20001, "name": "New Offer", "state": "active"},
    {"id": 30003, "name": "Archived Offer", "state": "active"},
    {"id": 40004, "name": "Fourth Offer", "state": "active"},
]


@pytest.fixture
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def make_campaign(session, *, schema="landings", status="synced", revision=3, offers=None):
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
    )
    session.add(f)
    session.flush()
    specs = offers if offers is not None else [
        dict(koi=18813, name="Flexacil", share=60, fixed=False, active=True),
        dict(koi=20001, name="New Offer", share=40, fixed=False, active=True),
        dict(koi=30003, name="Archived Offer", share=0, fixed=False, active=False),
    ]
    for spec in specs:
        active = spec["active"]
        session.add(models.CampaignOffer(
            flow_id=f.id,
            keitaro_offer_id=spec["koi"],
            offer_name=spec["name"],
            share=spec["share"],
            is_fixed=spec["fixed"],
            keitaro_state=spec.get("state", "active"),
            is_active=active,
            deleted_at=None if active else NOW,
        ))
    session.commit()
    return c, f


def mock_offers(m, rows=None):
    return m.get("offers").respond(json=OFFERS if rows is None else rows)


def flow_of(body):
    return next(f for f in body["flows"] if f["keitaro_flow_id"] == F1)


def shares(flow):
    return {o["keitaro_offer_id"]: o["share"] for o in flow["offers"]}


def offer_of(flow, offer_id):
    return next(o for o in flow["offers"] if o["keitaro_offer_id"] == offer_id)


def test_add_offer_redistributes_and_marks_modified(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        offers_route = mock_offers(m)
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 40004}, auth=AUTH)

    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert offers_route.called
    assert shares(flow) == {18813: 40, 20001: 27, 40004: 33}
    assert flow["shares_valid"] is True
    assert all(o["is_fixed"] is False for o in flow["offers"])
    assert [o["keitaro_offer_id"] for o in flow["offers"]] == [18813, 20001, 40004]
    assert [o["keitaro_offer_id"] for o in flow["deleted_offers"]] == [30003]
    assert flow["sync_status"] == "modified" and flow["revision"] == 4


def test_duplicate_active_offer_409_without_changes(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 18813}, auth=AUTH)

    assert r.status_code == 409 and r.json()["code"] == "DUPLICATE_OFFER"
    fresh = session.get(models.CampaignFlow, f.id)
    assert fresh.revision == 3 and fresh.sync_status == "synced"
    assert len(session.scalars(
        select(models.CampaignOffer).where(models.CampaignOffer.flow_id == f.id)
    ).all()) == 3


def test_add_archived_offer_restores_without_duplicate_row(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 30003}, auth=AUTH)

    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert shares(flow) == {18813: 40, 20001: 27, 30003: 33}
    assert flow["deleted_offers"] == []
    rows = session.scalars(
        select(models.CampaignOffer).where(models.CampaignOffer.flow_id == f.id)
    ).all()
    assert len(rows) == 3


def test_unknown_offer_falls_back_to_single_offer_endpoint(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        single = m.get("offers/99999").respond(
            json={"id": 99999, "name": "Fallback", "state": "active"}
        )
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH)

    assert r.status_code == 200, r.text
    assert single.called
    added = offer_of(flow_of(r.json()), 99999)
    assert added["offer_name"] == "Fallback" and added["name_unavailable"] is False


def test_add_missing_offer_uses_arbitrary_id_placeholder(client, session, dev_env):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        m.get("offers/99999").respond(404, json={"error": "not found"})
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH)

    assert r.status_code == 200, r.text
    added = offer_of(flow_of(r.json()), 99999)
    assert added["offer_name"] == "99999" and added["name_unavailable"] is True
    assert session.get(models.CampaignFlow, f.id).revision == 4


@pytest.mark.parametrize("status", [401, 403])
def test_arbitrary_offer_added_when_single_lookup_denied(client, session, status, dev_env):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        single = m.get("offers/99999").respond(status, json={"error": "Forbidden"})
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH)

    assert r.status_code == 200, r.text
    assert single.called
    added = offer_of(flow_of(r.json()), 99999)
    assert added["offer_name"] == "99999" and added["name_unavailable"] is True


def test_arbitrary_offer_added_when_offers_list_denied(client, session, dev_env):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        offers = m.get("offers").respond(403, json={"error": "Forbidden"})
        single = m.get("offers/99999").respond(403, json={"error": "Forbidden"})
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH)

    assert r.status_code == 200, r.text
    assert offers.called and single.called
    added = offer_of(flow_of(r.json()), 99999)
    assert added["offer_name"] == "99999" and added["name_unavailable"] is True


def test_offer_name_resolved_when_list_denied_but_single_ok(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        m.get("offers").respond(403, json={"error": "Forbidden"})
        m.get("offers/99999").respond(
            json={"id": 99999, "name": "Fallback", "state": "active"}
        )
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH)

    assert r.status_code == 200, r.text
    added = offer_of(flow_of(r.json()), 99999)
    assert added["offer_name"] == "Fallback" and added["name_unavailable"] is False


def test_production_rejects_arbitrary_offer_id(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        m.get("offers/99999").respond(404, json={"error": "not found"})
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "INVALID_REFERENCE"
    assert r.json()["details"] == {"field": "offer_id", "id": 99999}
    fresh = session.get(models.CampaignFlow, f.id)
    assert fresh.revision == 3 and fresh.sync_status == "synced"
    assert session.scalar(
        select(models.CampaignOffer).where(
            models.CampaignOffer.flow_id == f.id,
            models.CampaignOffer.keitaro_offer_id == 99999,
        )
    ) is None


def test_production_rejects_arbitrary_id_when_catalog_denies(client, session):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        m.get("offers/99999").respond(403, json={"error": "Forbidden"})
        r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "INVALID_REFERENCE"


def test_arbitrary_offer_supports_share_and_fixed(client, session, dev_env):
    c, f = make_campaign(session)
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        m.get("offers/99999").respond(404, json={"error": "not found"})
        added = client.post(
            f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 99999}, auth=AUTH
        )
    assert added.status_code == 200, added.text

    url = f"/api/campaigns/{c.id}/flows/{f.id}/offers/99999"
    patched = client.patch(url, json={"share": 30}, auth=AUTH)
    assert patched.status_code == 200, patched.text
    flow = flow_of(patched.json())
    assert shares(flow) == {18813: 42, 20001: 28, 99999: 30}
    assert offer_of(flow, 99999)["is_fixed"] is True


def test_delete_then_restore(client, session):
    c, f = make_campaign(session)
    d = client.delete(f"/api/campaigns/{c.id}/flows/{f.id}/offers/18813", auth=AUTH)
    assert d.status_code == 200, d.text
    flow = flow_of(d.json())
    assert shares(flow) == {20001: 100}
    assert [o["keitaro_offer_id"] for o in flow["deleted_offers"]] == [18813, 30003]
    assert flow["revision"] == 4 and flow["sync_status"] == "modified"

    r = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers/18813/restore", auth=AUTH)
    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert shares(flow) == {18813: 50, 20001: 50}
    assert [o["keitaro_offer_id"] for o in flow["deleted_offers"]] == [30003]
    assert flow["revision"] == 5


@pytest.mark.parametrize("min_share", [0, 1])
def test_delete_equalizes_remaining_free_offers(client, session, monkeypatch, min_share):
    monkeypatch.setattr(sc, "MIN_SHARE", min_share)
    c, f = make_campaign(session, offers=[
        dict(koi=18813, name="A", share=34, fixed=False, active=True),
        dict(koi=20001, name="B", share=33, fixed=False, active=True),
        dict(koi=40004, name="C", share=33, fixed=False, active=True),
    ])
    r = client.delete(f"/api/campaigns/{c.id}/flows/{f.id}/offers/40004", auth=AUTH)

    assert r.status_code == 200, r.text
    assert shares(flow_of(r.json())) == {18813: 50, 20001: 50}
    assert flow_of(r.json())["shares_valid"] is True


def test_delete_keeps_fixed_share_and_equalizes_free_offers(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, name="A", share=40, fixed=True, active=True),
        dict(koi=20001, name="B", share=30, fixed=False, active=True),
        dict(koi=40004, name="C", share=30, fixed=False, active=True),
    ])
    r = client.delete(f"/api/campaigns/{c.id}/flows/{f.id}/offers/40004", auth=AUTH)

    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert shares(flow) == {18813: 40, 20001: 60}
    assert offer_of(flow, 18813)["is_fixed"] is True


def test_delete_last_active_offer_is_allowed_locally(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, name="Only", share=100, fixed=False, active=True),
    ])
    r = client.delete(f"/api/campaigns/{c.id}/flows/{f.id}/offers/18813", auth=AUTH)

    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert flow["offers"] == [] and flow["shares_valid"] is False
    assert [o["keitaro_offer_id"] for o in flow["deleted_offers"]] == [18813]

    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        first = client.post(f"/api/campaigns/{c.id}/flows/{f.id}/offers", json={"offer_id": 40004}, auth=AUTH)
    assert first.status_code == 200, first.text
    assert shares(flow_of(first.json())) == {40004: 100}


def test_patch_share_pivots_and_sets_fixed(client, session):
    c, f = make_campaign(session)
    r = client.patch(f"/api/campaigns/{c.id}/flows/{f.id}/offers/18813", json={"share": 70}, auth=AUTH)

    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert shares(flow) == {18813: 70, 20001: 30}
    assert offer_of(flow, 18813)["is_fixed"] is True
    assert offer_of(flow, 20001)["is_fixed"] is False
    assert flow["revision"] == 4


@pytest.mark.parametrize("body", [{}, {"share": 50, "is_fixed": False}])
def test_invalid_patch(client, session, body):
    c, f = make_campaign(session)
    r = client.patch(f"/api/campaigns/{c.id}/flows/{f.id}/offers/18813", json=body, auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST"
    assert session.get(models.CampaignFlow, f.id).revision == 3


def test_fixed_toggle_recalculates(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, name="A", share=60, fixed=False, active=True),
        dict(koi=20001, name="B", share=30, fixed=False, active=True),
        dict(koi=40004, name="C", share=10, fixed=False, active=True),
    ])
    url = f"/api/campaigns/{c.id}/flows/{f.id}/offers/18813"

    on = client.patch(url, json={"is_fixed": True}, auth=AUTH)
    assert on.status_code == 200, on.text
    flow = flow_of(on.json())
    assert shares(flow) == {18813: 60, 20001: 30, 40004: 10}
    assert offer_of(flow, 18813)["is_fixed"] is True

    off = client.patch(url, json={"is_fixed": False}, auth=AUTH)
    assert off.status_code == 200, off.text
    flow = flow_of(off.json())
    # Снятие Fixed выравнивает все свободные доли; 1% остатка идёт первому.
    assert shares(flow) == {18813: 34, 20001: 33, 40004: 33}
    assert all(not o["is_fixed"] for o in flow["offers"])
    assert flow["revision"] == 5


@pytest.mark.parametrize("schema,state", [("redirect", "active"), ("landings", "disabled")])
def test_readonly_flow_allows_all_mutations(client, session, schema, state):
    """Демо-флага больше нет: мутации разрешены для всех потоков."""
    c, f = make_campaign(session, schema=schema, offers=[
        dict(koi=18813, name="Flexacil", share=100, fixed=False, active=True, state=state),
    ])
    base = f"/api/campaigns/{c.id}/flows/{f.id}"
    with respx.mock(base_url=BASE, assert_all_called=False) as m:
        mock_offers(m)
        results = [
            client.post(f"{base}/offers", json={"offer_id": 40004}, auth=AUTH),
            client.delete(f"{base}/offers/18813", auth=AUTH),
            client.post(f"{base}/offers/18813/restore", auth=AUTH),
            client.patch(f"{base}/offers/18813", json={"share": 50}, auth=AUTH),
        ]

    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert shares(flow_of(results[-1].json())) == {18813: 50, 40004: 50}
    assert session.get(models.CampaignFlow, f.id).revision == 7


def test_fixed_sum_exceeds_100_rejected(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, name="A", share=60, fixed=True, active=True),
        dict(koi=20001, name="B", share=60, fixed=True, active=True),
        dict(koi=40004, name="C", share=0, fixed=False, active=True),
    ])
    r = client.patch(f"/api/campaigns/{c.id}/flows/{f.id}/offers/40004", json={"share": 10}, auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "FIXED_SUM_EXCEEDS_100"
    assert session.get(models.CampaignFlow, f.id).revision == 3
    assert session.scalar(
        select(models.CampaignOffer.share).where(
            models.CampaignOffer.flow_id == f.id,
            models.CampaignOffer.keitaro_offer_id == 40004,
        )
    ) == 0


def test_delete_leaving_only_fixed_with_wrong_sum_rejected(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, name="A", share=70, fixed=True, active=True),
        dict(koi=20001, name="B", share=30, fixed=False, active=True),
    ])
    r = client.delete(f"/api/campaigns/{c.id}/flows/{f.id}/offers/20001", auth=AUTH)

    assert r.status_code == 422 and r.json()["code"] == "FIXED_SUM_MUST_BE_100"
    rows = session.scalars(
        select(models.CampaignOffer).where(models.CampaignOffer.flow_id == f.id)
    ).all()
    assert all(row.is_active for row in rows)
    assert session.get(models.CampaignFlow, f.id).revision == 3


def test_mutation_during_upload_keeps_status(client, session):
    c, f = make_campaign(session, status="uploading")
    r = client.patch(f"/api/campaigns/{c.id}/flows/{f.id}/offers/18813", json={"share": 70}, auth=AUTH)

    assert r.status_code == 200, r.text
    flow = flow_of(r.json())
    assert flow["sync_status"] == "uploading" and flow["revision"] == 4
    assert session.get(models.CampaignFlow, f.id).sync_status == "uploading"


def test_wrong_flow_or_offer_404(client, session):
    c, f = make_campaign(session)
    other = models.CampaignFlow(
        campaign_id=c.id, keitaro_flow_id=999999, name="Other", position=9,
        type="regular", schema="landings", state="active",
    )
    session.add(other)
    session.commit()

    assert client.patch(
        f"/api/campaigns/{c.id}/flows/{other.id}/offers/18813", json={"share": 50}, auth=AUTH
    ).status_code == 404
    assert client.delete(
        f"/api/campaigns/{c.id}/flows/{f.id}/offers/99999", auth=AUTH
    ).status_code == 404
    assert client.post(
        f"/api/campaigns/{c.id}/flows/{f.id}/offers/99999/restore", auth=AUTH
    ).status_code == 404
    assert client.get(f"/api/campaigns/{c.id + 1}", auth=AUTH).status_code == 404


def test_name_unavailable_marked_when_catalog_hides_name(client, session):
    c, f = make_campaign(session, offers=[
        dict(koi=18813, name="18813", share=100, fixed=False, active=True),
    ])
    r = client.get(f"/api/campaigns/{c.id}", auth=AUTH)

    assert r.status_code == 200
    assert offer_of(flow_of(r.json()), 18813)["name_unavailable"] is True
