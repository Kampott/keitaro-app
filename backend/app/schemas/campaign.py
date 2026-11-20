"""Схемы Campaign Creator (ТЗ §3.2–§3.6)."""
import re

from pydantic import BaseModel, Field, field_validator

from app.schemas.catalog import OfferItem, ReferenceItem
from app.services.catalog_service import country_codes


class CampaignCreateRequest(BaseModel):
    name: str
    geo: list[str]
    offer_id: int
    domain_id: int
    group_id: int
    source_id: int

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Name не может быть пустым")
        if len(v) > 255:
            raise ValueError("Name не может быть длиннее 255 символов")
        return v

    @field_validator("geo")
    @classmethod
    def _geo(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Выберите хотя бы одну страну GEO")
        known = country_codes()
        result: list[str] = []
        for raw in v:
            code = str(raw).strip().upper()
            if not re.fullmatch(r"[A-Z]{2}", code):
                raise ValueError(f"Некорректный код GEO: {raw!r}")
            if code not in known:
                raise ValueError(f"Неизвестный код GEO: {code}")
            if code not in result:
                result.append(code)
        if not result:
            raise ValueError("Выберите хотя бы одну страну GEO")
        return result


class StreamResult(BaseModel):
    id: int
    name: str
    flow_schema: str = Field(serialization_alias="schema")
    position: int


class CampaignCreateResult(BaseModel):
    status: str = "created"
    keitaro_id: int
    name: str
    alias: str
    tracking_url: str | None
    domain: ReferenceItem
    group: ReferenceItem
    source: ReferenceItem
    offer: OfferItem
    geo: list[str]
    streams: list[StreamResult]
    local_sync_failed: bool = False
    warning: str | None = None
