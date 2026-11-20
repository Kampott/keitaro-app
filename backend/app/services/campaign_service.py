"""Campaign Creator: создание кампании и потоков."""
import re
import secrets
import string

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.campaign import CampaignCreateRequest, CampaignCreateResult, StreamResult
from app.schemas.catalog import DomainItem, OfferItem, ReferenceItem
from app.services import sync_service
from app.services.catalog_service import CatalogService
from app.services.keitaro_client import KeitaroClient
from app.services.share_calculator import OfferInput, calculate_shares

_ALPHABET = string.ascii_lowercase + string.digits
_ALIAS_RETRIES = 3
_ALIAS_FIELD = re.compile(r"\balias\b", re.I)
_NAME_FIELD = re.compile(r"\bname\b", re.I)


def _new_alias() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


def _campaign_body(payload: CampaignCreateRequest, alias: str) -> dict:
    return {
        "name": payload.name,
        "alias": alias,
        "type": "position",
        "domain_id": payload.domain_id,
        "group_id": payload.group_id,  # при отклонении повторяем строкой
        "traffic_source_id": payload.source_id,
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,
    }


def _flow1(campaign_id: int, geo: list[str], redirect_url: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "name": "GEO to Google",
        "type": "regular",
        "schema": "redirect",
        "action_type": "http",
        "action_options": {"url": redirect_url},
        "position": 1,
        "state": "active",
        "collect_clicks": True,
        "filter_or": False,
        "filters": [{"name": "country", "mode": "accept", "payload": geo}],
    }


def _flow2(campaign_id: int, offers: list[dict]) -> dict:
    return {
        "campaign_id": campaign_id,
        "name": "Offer",
        "type": "regular",
        "schema": "landings",
        "action_type": "http",
        "position": 2,
        "state": "active",
        "collect_clicks": True,
        "offers": offers,
    }


def _offer_payload(offers: list[OfferItem]) -> list[dict]:
    """Справедливое целое распределение 100% между всеми выбранными офферами."""
    shares = {
        row.id: row.share
        for row in calculate_shares([OfferInput(id=offer.id, share=0) for offer in offers])
    }
    return [
        {"offer_id": offer.id, "share": shares[offer.id], "state": "active"}
        for offer in offers
    ]


def _recover_by_alias(client: KeitaroClient, alias: str) -> dict:
    """POST не дал ответа: ищем уже созданную кампанию полным проходом GET /campaigns."""
    limit, offset, matches, complete = 1000, 0, [], False
    while offset <= 100_000:
        try:
            page = client.request("GET", "campaigns", params={"limit": limit, "offset": offset})
        except AppError:
            break
        if not isinstance(page, list):
            break
        matches.extend(c for c in page if isinstance(c, dict) and c.get("alias") == alias)
        if len(page) < limit:
            complete = True
            break
        offset += limit
    if not complete:
        raise AppError(
            "KEITARO_LIST_INCOMPLETE", "Не удалось подтвердить полноту списка кампаний при поиске по alias",
            502, details={"alias": alias},
        )
    if len(matches) == 0:
        raise AppError(
            "CREATE_UNKNOWN_RESULT", "Кампания после обрыва ответа не найдена; повторный POST не выполнялся",
            502, details={"alias": alias},
        )
    if len(matches) > 1:
        raise AppError(
            "AMBIGUOUS_ALIAS", "Найдено несколько кампаний с таким alias; повторный POST не выполнялся",
            502, details={"alias": alias, "matches": len(matches)},
        )
    return matches[0]


def _campaign_id(campaign) -> int:
    if not isinstance(campaign, dict) or campaign.get("id") is None:
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro не вернул id созданной кампании", 502)
    try:
        return int(campaign["id"])
    except (TypeError, ValueError):
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro вернул некорректный id кампании", 502) from None


def _archive_failed(client: KeitaroClient, info: dict, alias: str, reason: str) -> dict:
    """Компенсация: сначала снимаем резервацию name/alias, затем архивируем."""
    keitaro_id = info["keitaro_id"]
    new_alias = _new_alias()
    # 255 - len("__failed_") - 8 (alias) = 238 — не превышаем лимит имени Keitaro.
    rename = {"name": f"{info['name'][:238]}__failed_{alias}", "alias": new_alias}
    details = {
        "reason": reason,
        "archived_campaign_id": keitaro_id,
        "archived": False,
        "rename_succeeded": False,
        "reserved_values": {"name": info["name"], "alias": alias},
    }
    try:
        client.request("PUT", f"campaigns/{keitaro_id}", json=rename)
        details["rename_succeeded"] = True
        details["reserved_values"] = {"name": rename["name"], "alias": new_alias}
    except AppError as e:
        details["rename_error"] = e.message
    try:
        client.request("DELETE", f"campaigns/{keitaro_id}", expect_json=False)
        details["archived"] = True
    except AppError as e:
        details["archive_error"] = e.message
    return details


def _tracking_url(domain: DomainItem, alias: str) -> str | None:
    """Scheme по is_ssl, имя без пробелов/префикса/слэша; wildcard → None."""
    name = (domain.name or "").strip()
    name = re.sub(r"^https?://", "", name, flags=re.I).strip().rstrip("/")
    if not name or "*" in name:
        return None
    scheme = "https" if domain.is_ssl else "http"
    return f"{scheme}://{name}/{alias}"


def _require(items, item_id: int, field: str):
    found = next((x for x in items if x.id == item_id), None)
    if found is None:
        raise AppError(
            "INVALID_REFERENCE", f"Не найден {field}={item_id} в справочниках Keitaro", 422,
            details={"field": field, "id": item_id},
        )
    return found


def _result(
    *, info: dict, domain: DomainItem, group: ReferenceItem, source: ReferenceItem,
    offers: list[OfferItem], streams: list[dict], local_sync_failed: bool = False,
    warning: str | None = None,
) -> CampaignCreateResult:
    return CampaignCreateResult(
        status="created_local_sync_failed" if local_sync_failed else "created",
        keitaro_id=info["keitaro_id"],
        name=info["name"],
        alias=info["alias"],
        tracking_url=_tracking_url(domain, info["alias"]),
        domain=domain,
        group=group,
        source=source,
        offers=offers,
        offer=offers[0],
        geo=info["geo"],
        streams=[
            StreamResult(id=int(s["id"]), name=str(s.get("name") or ""),
                         flow_schema=str(s.get("schema") or ""), position=int(s.get("position") or 0))
            for s in streams
        ],
        local_sync_failed=local_sync_failed,
        warning=warning,
    )


def create_campaign(
    client: KeitaroClient, catalog: CatalogService, session: Session, payload: CampaignCreateRequest,
) -> CampaignCreateResult:
    # 1. Валидация существования справочников
    domain = _require(catalog.domains(), payload.domain_id, "domain_id")
    group = _require(catalog.groups(), payload.group_id, "group_id")
    source = _require(catalog.sources(), payload.source_id, "source_id")
    offers: list[OfferItem] = []
    offer_names: dict[int, str] = {}
    for offer_id in payload.offer_ids or []:
        offer = catalog.find_offer(offer_id)
        if offer is None:
            raise AppError(
                "INVALID_REFERENCE", f"Не найден активный offer_id={offer_id}", 422,
                details={"field": "offer_id", "id": offer_id},
            )
        offers.append(offer)
        offer_names[offer.id] = offer.name
    offer_payload = _offer_payload(offers)

    # 2–3. Alias и POST /campaigns (с повтором только при ошибке по alias)
    last_alias_error: AppError | None = None
    campaign = None
    alias = ""
    for _ in range(_ALIAS_RETRIES):
        alias = _new_alias()
        body = _campaign_body(payload, alias)
        try:
            campaign = client.request("POST", "campaigns", json=body)
            break
        except AppError as e:
            if e.code == "KEITARO_UNREACHABLE":
                campaign = _recover_by_alias(client, alias)
                break
            if e.code != "KEITARO_VALIDATION":
                raise
            message = e.message.lower()
            if _NAME_FIELD.search(message):
                raise  # дубль имени — повторять нельзя
            if "group_id" in message:
                body["group_id"] = str(payload.group_id)
                campaign = client.request("POST", "campaigns", json=body)
                break
            if _ALIAS_FIELD.search(message):
                last_alias_error = e
                continue
            raise
    if campaign is None:
        raise AppError(
            "KEITARO_VALIDATION", "Не удалось подобрать уникальный alias за 3 попытки", 422,
            details={"last": last_alias_error.message if last_alias_error else None},
        )

    keitaro_id = _campaign_id(campaign)
    info = {
        "keitaro_id": keitaro_id,
        "name": payload.name,
        "alias": alias,
        "geo": payload.geo,
        "domain_id": payload.domain_id,
        "group_id": payload.group_id,
        "source_id": payload.source_id,
        "offer_names": offer_names,
    }
    redirect_url = get_settings().google_redirect_url

    # 4. Два потока последовательно, без автоповтора
    streams_created: list[dict] = []
    for body in (_flow1(keitaro_id, payload.geo, redirect_url), _flow2(keitaro_id, offer_payload)):
        try:
            stream = client.request("POST", "streams", json=body)
        except AppError as e:
            details = _archive_failed(client, info, alias, f"POST /streams: {e.message}")
            raise AppError(
                "CAMPAIGN_CREATE_FAILED", "Не удалось создать поток: кампания архивирована", 502, details=details
            ) from e
        if not isinstance(stream, dict) or stream.get("id") is None:
            details = _archive_failed(client, info, alias, "POST /streams не вернул id потока")
            raise AppError("CAMPAIGN_CREATE_FAILED", "Кампания архивирована", 502, details=details)
        streams_created.append(stream)

    # 5. Fetch + проверка структуры; при расхождении — архивация
    try:
        remote, remote_streams = sync_service.fetch_remote(client, keitaro_id)
        active = sync_service.verify_creator_structure(remote_streams)
    except sync_service.StructureMismatch as e:
        details = _archive_failed(client, info, alias, f"structure: {e}")
        raise AppError(
            "CAMPAIGN_CREATE_FAILED", "Структура созданной кампании не соответствует ожидаемой", 502,
            details=details,
        ) from e
    except sync_service.RemoteReadError:
        return _result(
            info=info, domain=domain, group=group, source=source, offers=offers,
            streams=streams_created, local_sync_failed=True,
            warning="Кампания создана в Keitaro, но прочитать её для локальной копии не удалось. Выполните Fetch в Edit Campaign.",
        )

    # 7. Ошибка БД не ведёт к архивации
    try:
        sync_service.store_campaign(session, remote, active, info=info, operation="create")
    except sync_service.LocalStoreError as e:
        return _result(
            info=info, domain=domain, group=group, source=source, offers=offers,
            streams=active, local_sync_failed=True,
            warning=f"Кампания создана в Keitaro, локальная копия не подготовлена: {e}",
        )

    return _result(
        info=info, domain=domain, group=group, source=source, offers=offers, streams=active,
    )
