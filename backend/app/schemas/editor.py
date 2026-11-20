"""Схемы чтения Campaign Editor."""
from datetime import datetime

from pydantic import BaseModel, Field


class OfferDetail(BaseModel):
    id: int
    keitaro_offer_id: int
    offer_name: str
    share: int
    is_fixed: bool
    keitaro_state: str
    is_active: bool
    readonly: bool
    name_unavailable: bool = False


class FlowDetail(BaseModel):
    id: int
    keitaro_flow_id: int
    name: str
    position: int
    flow_type: str = Field(serialization_alias="type")
    flow_schema: str = Field(serialization_alias="schema")
    state: str
    sync_status: str
    revision: int
    shares_valid: bool
    shares_sum: int
    readonly: bool
    last_error: str | None
    last_fetched_at: datetime | None
    last_uploaded_at: datetime | None
    offers: list[OfferDetail]
    deleted_offers: list[OfferDetail]


class CampaignSummary(BaseModel):
    id: int
    keitaro_id: int
    name: str
    alias: str
    status: str
    domain_id: int | None
    group_id: int
    source_id: int
    last_fetched_at: datetime | None


class CampaignDetail(CampaignSummary):
    flows: list[FlowDetail]


class FetchByKeitaroRequest(BaseModel):
    keitaro_id: int
    force: bool = False


class OfferAddRequest(BaseModel):
    offer_id: int


class OfferPatchRequest(BaseModel):
    share: int | None = Field(default=None, ge=0, le=100)
    is_fixed: bool | None = None
