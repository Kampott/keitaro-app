from fastapi import APIRouter, Depends, Query

from app.api.deps import get_catalog, get_keitaro
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.catalog import (
    Defaults, DomainItem, GroupCreate, KeitaroCampaignItem, OfferItem, ReferenceItem,
)
from app.services import keitaro_campaign_service
from app.services.catalog_service import CatalogService
from app.services.keitaro_client import KeitaroClient

router = APIRouter(prefix="/keitaro")


@router.get("/ping")
def ping(keitaro: KeitaroClient = Depends(get_keitaro)):
    """Проверка URL и ключа: наружу идёт только счётчик, сырой ответ Keitaro (там есть token) не отдаём."""
    campaigns = keitaro.request("GET", "campaigns", params={"limit": 1})
    if not isinstance(campaigns, list):
        raise AppError("KEITARO_BAD_RESPONSE", "Неожиданная форма ответа Keitaro", 502)
    return {"ok": True, "campaigns_returned": len(campaigns)}


@router.get("/campaigns", response_model=list[KeitaroCampaignItem])
def remote_campaigns(
    search: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    client: KeitaroClient = Depends(get_keitaro),
):
    """Кампании Keitaro для выбора в Editor; поиск по name/alias/ID на backend."""
    return keitaro_campaign_service.list_remote(client, search=search, limit=limit, offset=offset)


@router.get("/defaults", response_model=Defaults)
def defaults():
    """Значения по умолчанию из .env — без обращения к Keitaro."""
    s = get_settings()
    return Defaults(
        domain_id=s.keitaro_default_domain_id,
        group_id=s.keitaro_default_group_id,
        source_id=s.keitaro_default_traffic_source_id,
        google_redirect_url=s.google_redirect_url,
    )


@router.get("/domains", response_model=list[DomainItem])
def domains(catalog: CatalogService = Depends(get_catalog)):
    return catalog.domains()


@router.get("/groups", response_model=list[ReferenceItem])
def groups(catalog: CatalogService = Depends(get_catalog)):
    return catalog.groups()


@router.post("/groups", response_model=ReferenceItem, status_code=201)
def create_group(body: GroupCreate, catalog: CatalogService = Depends(get_catalog)):
    """D4: создать группу кампаний; position назначает Keitaro."""
    return catalog.create_group(body.name)


@router.get("/sources", response_model=list[ReferenceItem])
def sources(catalog: CatalogService = Depends(get_catalog)):
    return catalog.sources()


@router.get("/offers", response_model=list[OfferItem])
def offers(
    search: str = "",
    limit: int = Query(20, ge=1),
    catalog: CatalogService = Depends(get_catalog),
):
    """Кэш полного каталога 60 с; только активные офферы, не более 20."""
    return catalog.search_offers(search, limit)
