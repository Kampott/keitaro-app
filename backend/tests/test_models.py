"""Тесты моделей и ограничений на PostgreSQL (отдельная БД adrobot_test)."""
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db import models  # noqa: F401
from app.db.database import Base


def _campaign(s):
    c = models.Campaign(
        keitaro_id=216227, name="test", alias="WVRH2s",
        group_id=10489, source_id=836, domain_id=1813,
    )
    s.add(c)
    s.flush()
    return c


def _flow(s, campaign):
    f = models.CampaignFlow(campaign=campaign, keitaro_flow_id=1329768, name="Flow 2")
    s.add(f)
    s.flush()
    return f


def test_tables_and_defaults(session):
    assert {"campaigns", "campaign_flows", "campaign_offers", "sync_logs"} <= set(Base.metadata.tables)
    c = _campaign(session)
    f = _flow(session, c)
    assert f.revision == 0 and f.sync_status == "synced" and f.schema == "landings"
    o = models.CampaignOffer(flow=f, keitaro_offer_id=18813, offer_name="Offer", share=100)
    session.add(o)
    session.flush()
    assert o.is_active is True and o.is_fixed is False and o.keitaro_state == "active"


def test_unique_flow_offer(session):
    c = _campaign(session)
    f = _flow(session, c)
    session.add_all([
        models.CampaignOffer(flow=f, keitaro_offer_id=18813, share=60),
        models.CampaignOffer(flow=f, keitaro_offer_id=18813, share=40),
    ])
    with pytest.raises(IntegrityError):
        session.flush()


def test_share_check(session):
    c = _campaign(session)
    f = _flow(session, c)
    session.add(models.CampaignOffer(flow=f, keitaro_offer_id=1, share=101))
    with pytest.raises(IntegrityError):
        session.flush()


def test_soft_delete_check(session):
    c = _campaign(session)
    f = _flow(session, c)
    o = models.CampaignOffer(flow=f, keitaro_offer_id=1, share=100)
    session.add(o)
    session.flush()
    o.is_active = False  # без deleted_at — нарушение CHECK
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleted_at_requires_inactive(session):
    c = _campaign(session)
    f = _flow(session, c)
    o = models.CampaignOffer(flow=f, keitaro_offer_id=1, share=100)
    session.add(o)
    session.flush()
    from datetime import datetime, timezone
    o.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with pytest.raises(IntegrityError):
        session.flush()


def test_constraints_in_metadata(session):
    insp = inspect(session.bind)
    uniques = {x["name"] for x in insp.get_unique_constraints("campaign_offers") if x.get("name")}
    checks = {x["name"] for x in insp.get_check_constraints("campaign_offers") if x.get("name")}
    assert "uq_offer_flow_keitaro" in uniques
    assert {"ck_offer_share", "ck_offer_active_deleted"} <= checks


def test_sync_log_and_cascade(session):
    c = _campaign(session)
    f = _flow(session, c)
    session.add(models.CampaignOffer(flow=f, keitaro_offer_id=1, share=100))
    session.add(models.SyncLog(campaign=c, flow=f, operation="fetch", status="success", message="ok"))
    session.flush()
    session.delete(f)
    session.flush()
    assert session.query(models.CampaignOffer).count() == 0
    assert session.query(models.SyncLog).count() == 0