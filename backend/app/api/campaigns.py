from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_catalog, get_db, get_keitaro
from app.schemas.campaign import CampaignCreateRequest, CampaignCreateResult
from app.schemas.editor import (
    CampaignDetail, CampaignSummary, FetchByKeitaroRequest, OfferAddRequest, OfferPatchRequest,
)
from app.services import editor_service, offer_service
from app.services.campaign_service import create_campaign
from app.services.catalog_service import CatalogService
from app.services.keitaro_client import KeitaroClient

router = APIRouter(prefix="/campaigns")


@router.post("", response_model=CampaignCreateResult)
def create(
    body: CampaignCreateRequest,
    client: KeitaroClient = Depends(get_keitaro),
    catalog: CatalogService = Depends(get_catalog),
    session: Session = Depends(get_db),
):
    """Создать кампанию Keitaro (§3.5) и подготовить её локальную копию."""
    return create_campaign(client, catalog, session, body)


@router.post("/fetch", response_model=CampaignDetail)
def fetch_by_keitaro_id(
    body: FetchByKeitaroRequest,
    client: KeitaroClient = Depends(get_keitaro),
    catalog: CatalogService = Depends(get_catalog),
    session: Session = Depends(get_db),
):
    """§4.2: выбрать кампанию Keitaro; при первом выборе создаётся локальная копия."""
    return editor_service.fetch_new_campaign(
        client, catalog, session, body.keitaro_id, force=body.force
    )


@router.get("", response_model=list[CampaignSummary])
def list_local(session: Session = Depends(get_db)):
    """Локальные кампании с агрегированным статусом (§4.10)."""
    return editor_service.list_campaigns(session)


@router.get("/{campaign_id}", response_model=CampaignDetail)
def get_local(campaign_id: int, session: Session = Depends(get_db)):
    """Потоки, офферы и статус локальной копии кампании (§4.3, §4.8)."""
    return editor_service.get_campaign(session, campaign_id)


@router.post("/{campaign_id}/fetch", response_model=CampaignDetail)
def fetch(
    campaign_id: int,
    force: bool = False,
    client: KeitaroClient = Depends(get_keitaro),
    catalog: CatalogService = Depends(get_catalog),
    session: Session = Depends(get_db),
):
    """Fetch from Keitaro (§4.8); force=true перезаписывает локальные изменения."""
    return editor_service.fetch_campaign(client, catalog, session, campaign_id, force=force)


@router.post("/{campaign_id}/flows/{flow_id}/offers", response_model=CampaignDetail)
def add_offer(
    campaign_id: int,
    flow_id: int,
    body: OfferAddRequest,
    allow_readonly: bool = False,
    client: KeitaroClient = Depends(get_keitaro),
    catalog: CatalogService = Depends(get_catalog),
    session: Session = Depends(get_db),
):
    """§4.4: добавить оффер в поток (из каталога или из Deleted Offers).

    `allow_readonly=true` — демо-режим: разрешает мутации читаемых потоков (§4.2).
    """
    return offer_service.add_offer(
        client, catalog, session, campaign_id, flow_id, body.offer_id,
        allow_readonly=allow_readonly,
    )


@router.delete("/{campaign_id}/flows/{flow_id}/offers/{offer_id}", response_model=CampaignDetail)
def delete_offer(
    campaign_id: int,
    flow_id: int,
    offer_id: int,
    allow_readonly: bool = False,
    session: Session = Depends(get_db),
):
    """§4.5: мягко удалить оффер в Deleted Offers."""
    return offer_service.delete_offer(
        session, campaign_id, flow_id, offer_id, allow_readonly=allow_readonly
    )


@router.post(
    "/{campaign_id}/flows/{flow_id}/offers/{offer_id}/restore", response_model=CampaignDetail
)
def restore_offer(
    campaign_id: int,
    flow_id: int,
    offer_id: int,
    allow_readonly: bool = False,
    session: Session = Depends(get_db),
):
    """§4.5: восстановить оффер из Deleted Offers."""
    return offer_service.restore_offer(
        session, campaign_id, flow_id, offer_id, allow_readonly=allow_readonly
    )


@router.patch("/{campaign_id}/flows/{flow_id}/offers/{offer_id}", response_model=CampaignDetail)
def patch_offer(
    campaign_id: int,
    flow_id: int,
    offer_id: int,
    body: OfferPatchRequest,
    allow_readonly: bool = False,
    session: Session = Depends(get_db),
):
    """§4.6: задать share (D1: становится Fixed) или переключить Fixed."""
    return offer_service.patch_offer(
        session, campaign_id, flow_id, offer_id,
        share=body.share, is_fixed=body.is_fixed, allow_readonly=allow_readonly,
    )
