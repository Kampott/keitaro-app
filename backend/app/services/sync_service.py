"""Чтение удалённого состояния и локальная запись."""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models
from app.services.keitaro_client import KeitaroClient


class RemoteReadError(Exception):
    """Сетевая ошибка при чтении: кампания в Keitaro корректна, архивация не нужна."""


class StructureMismatch(Exception):
    """Прочитанная структура не соответствует Campaign Creator: нужна архивация."""


class LocalStoreError(Exception):
    """Ошибка записи в локальную БД: архивация не нужна."""


_HASH_FIELDS = (
    "name", "type", "schema", "state", "position", "action_type",
    "action_options", "filters", "offers", "landings",
)

# Поля схемы StreamRequestPut. Служебные id/created_at/updated_at
# и неописанные в схеме поля не отправляем обратно в Keitaro.
_STREAM_REQUEST_FIELDS = (
    "campaign_id", "type", "name", "position", "weight", "action_options",
    "comments", "state", "action_type", "schema", "collect_clicks",
    "filter_or", "filters", "triggers", "landings", "offers",
)


def _stable_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def flow_remote_hash(stream: dict) -> str:
    """Стабильный хэш значимых полей потока — используется для REMOTE_CHANGED при Upload."""
    return _stable_hash({k: stream.get(k) for k in _HASH_FIELDS})


def hash_without_offers(stream: dict) -> str:
    """Хэш потока без offers: нужно понять, не затёр ли частичный PUT другие поля."""
    return _stable_hash({k: stream.get(k) for k in _HASH_FIELDS if k != "offers"})


def stream_request_payload(stream: dict) -> dict:
    """Тело для полного PUT /streams/{id}: только поля схемы StreamRequestPut."""
    payload = {k: stream[k] for k in _STREAM_REQUEST_FIELDS if k in stream}
    offers = payload.get("offers")
    if isinstance(offers, list):
        # OfferStreamRequest: offer_id/share/state; служебные id и stream_id не нужны.
        payload["offers"] = [
            {k: row[k] for k in ("offer_id", "share", "state") if k in row}
            for row in offers if isinstance(row, dict)
        ]
    return payload


def fetch_remote(client: KeitaroClient, keitaro_id: int) -> tuple[dict, list[dict]]:
    try:
        campaign = client.request("GET", f"campaigns/{keitaro_id}")
        streams = client.request("GET", f"campaigns/{keitaro_id}/streams")
    except AppError as e:
        if e.code == "KEITARO_UNREACHABLE":
            raise RemoteReadError(e.message) from e
        raise
    if not isinstance(campaign, dict) or not isinstance(streams, list):
        raise AppError("KEITARO_BAD_RESPONSE", "Неожиданная форма ответа Keitaro при Fetch", 502)
    return campaign, streams


def verify_creator_structure(streams: list[dict]) -> list[dict]:
    """Ровно два потока (кроме deleted): первый redirect, второй landings по position."""
    active = [s for s in streams if isinstance(s, dict) and s.get("state") != "deleted"]

    def position(s: dict) -> int:
        try:
            return int(s.get("position") or 0)
        except (TypeError, ValueError):
            return 0

    active.sort(key=position)
    if len(active) != 2:
        raise StructureMismatch(f"Ожидалось 2 активных потока, получено {len(active)}")
    schemas = [s.get("schema") for s in active]
    if schemas != ["redirect", "landings"]:
        raise StructureMismatch(f"Ожидались schema redirect и landings по порядку, получено {schemas}")
    return active


def store_campaign(
    session: Session,
    campaign: dict,
    streams: list[dict],
    *,
    info: dict,
    operation: str = "create",
) -> None:
    """Одной транзакцией пишем кампанию, потоки, офферы и SyncLog."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    offer_names: dict[int, str] = info.get("offer_names", {})
    try:
        row = models.Campaign(
            keitaro_id=int(campaign["id"]),
            name=str(campaign.get("name") or info["name"]),
            alias=str(campaign.get("alias") or info["alias"]),
            domain_id=info.get("domain_id"),
            group_id=int(campaign.get("group_id") or info["group_id"]),
            source_id=int(campaign.get("traffic_source_id") or info["source_id"]),
            last_fetched_at=now,
        )
        session.add(row)
        session.flush()

        for stream in streams:
            flow = models.CampaignFlow(
                campaign_id=row.id,
                keitaro_flow_id=int(stream["id"]),
                name=str(stream.get("name") or ""),
                position=int(stream.get("position") or 0),
                type=str(stream.get("type") or "regular"),
                schema=str(stream.get("schema") or "landings"),
                state=str(stream.get("state") or "active"),
                sync_status="synced",
                revision=0,
                remote_hash=flow_remote_hash(stream),
                remote_payload=stream_request_payload(stream),
                last_fetched_at=now,
            )
            session.add(flow)
            session.flush()

            for remote_offer in stream.get("offers") or []:
                if not isinstance(remote_offer, dict):
                    continue
                offer_id = int(remote_offer["offer_id"])
                state = str(remote_offer.get("state") or "active")
                is_active = state == "active"
                session.add(models.CampaignOffer(
                    flow_id=flow.id,
                    keitaro_offer_id=offer_id,
                    offer_name=offer_names.get(offer_id, str(offer_id)),
                    share=int(remote_offer.get("share") or 0),
                    keitaro_state=state,
                    is_fixed=False,
                    is_active=is_active,
                    deleted_at=None if is_active else now,
                ))

            session.add(models.SyncLog(
                campaign_id=row.id,
                flow_id=flow.id,
                operation=operation,
                status="success",
                message=f"Fetch: поток {flow.keitaro_flow_id}",
            ))

        session.commit()
    except Exception as e:
        session.rollback()
        raise LocalStoreError(str(e)) from e
