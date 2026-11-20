"""Схемы Campaign Creator (ТЗ §3.2–§3.6)."""
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.catalog import OfferItem, ReferenceItem
from app.services.catalog_service import country_codes

MAX_CREATE_OFFERS = 20


class CampaignCreateRequest(BaseModel):
    name: str
    geo: list[str]
    domain_id: int
    group_id: int
    source_id: int
    # offer_id сохранён для обратной совместимости; UI шлёт offer_ids.
    offer_id: int | None = None
    offer_ids: list[int] | None = None

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

    @model_validator(mode="after")
    def _normalize_offers(self) -> "CampaignCreateRequest":
        ids = self.offer_ids if self.offer_ids is not None else (
            [self.offer_id] if self.offer_id is not None else []
        )
        if not ids:
            raise ValueError("Укажите хотя бы один Offer")
        if any(offer_id <= 0 for offer_id in ids):
            raise ValueError("Offer ID должен быть положительным целым числом")
        if len(set(ids)) != len(ids):
            raise ValueError("Offer ID не должны повторяться")
        if len(ids) > MAX_CREATE_OFFERS:
            raise ValueError(f"Можно указать не более {MAX_CREATE_OFFERS} офферов")
        self.offer_ids = ids
        if self.offer_id is None:
            self.offer_id = ids[0]
        return self


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
    offers: list[OfferItem]
    # Оставлен для совместимости с API-клиентами, ожидавшими один оффер.
    offer: OfferItem
    geo: list[str]
    streams: list[StreamResult]
    local_sync_failed: bool = False
    warning: str | None = None
