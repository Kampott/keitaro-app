"""Campaign Editor: чтение локального состояния и Fetch."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.db import models
from app.schemas import editor
from app.services import sync_service
from app.services.catalog_service import CatalogService
from app.services.keitaro_client import KeitaroClient
from app.services.share_calculator import shares_valid

_STATUS_RANK = {"synced": 0, "modified": 1, "uploading": 2, "error": 3}
_GUARDED = ("modified", "error")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _campaign_or_404(session: Session, campaign_id: int) -> models.Campaign:
    row = session.get(models.Campaign, campaign_id)
    if row is None:
        raise AppError("NOT_FOUND", f"Локальная кампания {campaign_id} не найдена", 404)
    return row


def campaign_status(flows: list[models.CampaignFlow]) -> str:
    """Наихудший статус потоков: error > uploading > modified > synced."""
    if not flows:
        return "synced"
    return max(flows, key=lambda f: _STATUS_RANK.get(f.sync_status, 0)).sync_status


def _last_error(session: Session, flow_id: int) -> str | None:
    return session.scalar(
        select(models.SyncLog.message)
        .where(models.SyncLog.flow_id == flow_id, models.SyncLog.status == "error")
        .order_by(models.SyncLog.id.desc())
    )


def _offer_dict(row: models.CampaignOffer, readonly: bool) -> dict:
    return {
        "id": row.id,
        "keitaro_offer_id": row.keitaro_offer_id,
        "offer_name": row.offer_name,
        "share": row.share,
        "is_fixed": row.is_fixed,
        "keitaro_state": row.keitaro_state,
        "is_active": row.is_active,
        "readonly": readonly,
        "name_unavailable": not row.offer_name or row.offer_name == str(row.keitaro_offer_id),
    }


def _flow_dict(
    session: Session, flow: models.CampaignFlow, offers: list[models.CampaignOffer] | None = None
) -> dict:
    all_offers = list(flow.offers) if offers is None else offers
    readonly = flow.schema != "landings" or any(o.keitaro_state != "active" for o in all_offers)
    active = [o for o in all_offers if o.is_active]
    archived = [o for o in all_offers if not o.is_active]
    return {
        "id": flow.id,
        "keitaro_flow_id": flow.keitaro_flow_id,
        "name": flow.name,
        "position": flow.position,
        "flow_type": flow.type,
        "flow_schema": flow.schema,
        "state": flow.state,
        "sync_status": flow.sync_status,
        "revision": flow.revision,
        "shares_valid": shares_valid([o.share for o in active]),
        # frontend отображает сумму из ответа backend и не считает shares сам
        "shares_sum": sum(o.share for o in active),
        "readonly": readonly,
        "last_error": _last_error(session, flow.id),
        "last_fetched_at": flow.last_fetched_at,
        "last_uploaded_at": flow.last_uploaded_at,
        "offers": [_offer_dict(o, readonly or o.keitaro_state != "active") for o in active],
        "deleted_offers": [_offer_dict(o, readonly or o.keitaro_state != "active") for o in archived],
    }


def _campaign_dict(
    session: Session,
    campaign: models.Campaign,
    *,
    flows: list[models.CampaignFlow] | None = None,
    offers_by_flow: dict | None = None,
    include_flows: bool = True,
) -> dict:
    all_flows = list(campaign.flows) if flows is None else flows
    visible = [f for f in all_flows if f.state != "deleted"]
    data = {
        "id": campaign.id,
        "keitaro_id": campaign.keitaro_id,
        "name": campaign.name,
        "alias": campaign.alias,
        "status": campaign_status(visible),
        "domain_id": campaign.domain_id,
        "group_id": campaign.group_id,
        "source_id": campaign.source_id,
        "last_fetched_at": campaign.last_fetched_at,
    }
    if include_flows:
        data["flows"] = [
            _flow_dict(
                session,
                f,
                None if offers_by_flow is None else offers_by_flow.get(f),
            )
            for f in visible
        ]
    return data


def list_campaigns(session: Session) -> list[editor.CampaignSummary]:
    rows = session.scalars(select(models.Campaign).order_by(models.Campaign.id)).all()
    return [
        editor.CampaignSummary(**_campaign_dict(session, row, include_flows=False))
        for row in rows
    ]


def get_campaign(session: Session, campaign_id: int) -> editor.CampaignDetail:
    campaign = _campaign_or_404(session, campaign_id)
    return editor.CampaignDetail(**_campaign_dict(session, campaign))


def _write_error_log(session: Session, campaign_id: int, message: str) -> None:
    """Best-effort: inability to write SyncLog must not mask the original error."""
    try:
        with session.begin_nested():
            session.add(models.SyncLog(
                campaign_id=campaign_id,
                flow_id=None,
                operation="fetch",
                status="error",
                message=(message or "")[:2000],
            ))
        # get_db не коммитит за endpoint: без явного commit лог останется в
        # незакоммиченной транзакции и будет потерян при закрытии сессии.
        session.commit()
    except Exception:
        pass


def _guard(flows: list[models.CampaignFlow], *, force: bool) -> None:
    busy = [f.id for f in flows if f.sync_status == "uploading"]
    if busy:
        raise AppError("BUSY", "Поток занят Upload", 409, details={"flows": busy})
    changed = [f.id for f in flows if f.sync_status in _GUARDED]
    if changed and not force:
        raise AppError(
            "LOCAL_CHANGES", "Есть локальные изменения; повторите с force=true", 409,
            details={"flows": changed},
        )


def fetch_campaign(
    client: KeitaroClient,
    catalog: CatalogService,
    session: Session,
    campaign_id: int,
    *,
    force: bool = False,
) -> editor.CampaignDetail:
    """Прочитать Keitaro и атомарно заменить локальную копию кампании."""
    campaign = _campaign_or_404(session, campaign_id)
    snapshot = {f.id: (f.sync_status, f.revision) for f in campaign.flows}
    _guard(list(campaign.flows), force=force)

    # 2. Сетевые вызовы до захвата блокировок; при ошибке локальные данные не трогаем.
    try:
        offer_rows = catalog.refresh_offers()
        remote, streams = sync_service.fetch_remote(client, campaign.keitaro_id)
    except sync_service.RemoteReadError as e:
        _write_error_log(session, campaign.id, e.message)
        raise AppError("KEITARO_UNREACHABLE", e.message, 502) from e
    except AppError as e:
        _write_error_log(session, campaign.id, e.message)
        raise

    if not isinstance(remote, dict) or remote.get("id") is None:
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro не вернул кампанию при Fetch", 502)
    offer_names: dict[int, str] = {}
    for row in offer_rows:
        try:
            offer_names[int(row["id"])] = str(row.get("name") or "")
        except (KeyError, TypeError, ValueError):
            continue
    remote_ids: set[int] = set()
    for stream in streams:
        if not isinstance(stream, dict) or stream.get("id") is None:
            raise AppError("KEITARO_BAD_RESPONSE", "Неверная форма потока Keitaro при Fetch", 502)
        remote_ids.add(_int(stream["id"]))

    # 3. Блокировки в стабильном порядке, повторная проверка снимка.
    locked = session.scalar(
        select(models.Campaign).where(models.Campaign.id == campaign_id).with_for_update()
    )
    if locked is None:
        raise AppError("NOT_FOUND", f"Локальная кампания {campaign_id} не найдена", 404)
    locked_flows = session.scalars(
        select(models.CampaignFlow)
        .where(models.CampaignFlow.campaign_id == campaign_id)
        .order_by(models.CampaignFlow.id)
        .with_for_update()
    ).all()
    _guard(list(locked_flows), force=force)
    changed = [
        f.id for f in locked_flows
        if snapshot.get(f.id) != (f.sync_status, f.revision)
    ]
    if changed:
        raise AppError(
            "LOCAL_CHANGES", "Поток изменился во время Fetch", 409, details={"flows": changed}
        )

    now = _now()
    result_flows: list[models.CampaignFlow] = []
    offers_by_flow: dict[models.CampaignFlow, list[models.CampaignOffer]] = {}
    existing_by_kf = {f.keitaro_flow_id: f for f in locked_flows}

    try:
        # Поля кампании. domain_id в 11.4 есть в ответе — обновляем.
        locked.name = str(remote.get("name") or locked.name)
        locked.alias = str(remote.get("alias") or locked.alias)
        if remote.get("group_id") is not None:
            locked.group_id = _int(remote["group_id"], locked.group_id)
        if remote.get("traffic_source_id") is not None:
            locked.source_id = _int(remote["traffic_source_id"], locked.source_id)
        if remote.get("domain_id") is not None:
            locked.domain_id = _int(remote["domain_id"], locked.domain_id)
        locked.last_fetched_at = now

        for stream in streams:
            kfid = _int(stream["id"])
            flow = existing_by_kf.get(kfid)
            if flow is None:
                flow = models.CampaignFlow(
                    campaign_id=locked.id,
                    keitaro_flow_id=kfid,
                    name=str(stream.get("name") or ""),
                    position=_int(stream.get("position")),
                    type=str(stream.get("type") or "regular"),
                    schema=str(stream.get("schema") or "landings"),
                    state=str(stream.get("state") or "active"),
                )
                session.add(flow)
                session.flush()  # офферам нужен уже существующий flow.id
            flow.name = str(stream.get("name") or "")
            flow.position = _int(stream.get("position"))
            flow.type = str(stream.get("type") or "regular")
            flow.schema = str(stream.get("schema") or "landings")
            flow.state = str(stream.get("state") or "active")
            flow.sync_status = "synced"
            flow.revision = 0
            flow.remote_hash = sync_service.flow_remote_hash(stream)
            flow.remote_payload = sync_service.stream_request_payload(stream)
            flow.last_fetched_at = now
            result_flows.append(flow)

            current = list(flow.offers)
            by_oid = {o.keitaro_offer_id: o for o in current}
            seen: set[int] = set()
            for remote_offer in stream.get("offers") or []:
                if not isinstance(remote_offer, dict) or remote_offer.get("offer_id") is None:
                    raise AppError("KEITARO_BAD_RESPONSE", "Неверная форма оффера в потоке Keitaro", 502)
                oid = _int(remote_offer["offer_id"])
                seen.add(oid)
                state = str(remote_offer.get("state") or "active")
                row = by_oid.get(oid)
                if row is None:
                    row = models.CampaignOffer(
                        flow_id=flow.id, keitaro_offer_id=oid, is_fixed=False
                    )
                    session.add(row)
                    current.append(row)
                    by_oid[oid] = row
                row.share = _int(remote_offer.get("share"))
                row.keitaro_state = state
                # is_fixed сохраняем у существующей строки.
                row.is_active = state == "active"
                row.deleted_at = None if row.is_active else now
                row.offer_name = offer_names.get(oid, row.offer_name or str(oid))
            for row in current:
                if row.keitaro_offer_id not in seen and row.is_active:
                    row.is_active = False
                    row.deleted_at = now
            offers_by_flow[flow] = current

        for flow in locked_flows:
            if flow.keitaro_flow_id not in remote_ids:
                flow.state = "deleted"  # скрываем в UI, данные не удаляем
                result_flows.append(flow)
                offers_by_flow[flow] = list(flow.offers)

        session.flush()
        for flow in result_flows:
            if flow.keitaro_flow_id in remote_ids:
                session.add(models.SyncLog(
                    campaign_id=locked.id,
                    flow_id=flow.id,
                    operation="fetch",
                    status="success",
                    message=f"Fetch: поток {flow.keitaro_flow_id}",
                ))
        session.flush()

        response = editor.CampaignDetail(
            **_campaign_dict(session, locked, flows=result_flows, offers_by_flow=offers_by_flow)
        )
        session.commit()
        return response
    except Exception as e:
        session.rollback()
        _write_error_log(session, campaign.id, f"Fetch: {e}")
        if isinstance(e, AppError):
            raise
        raise AppError(
            "LOCAL_DB_ERROR", "Ошибка записи локальной копии", 500, details={"detail": str(e)}
        ) from e


def fetch_new_campaign(
    client: KeitaroClient,
    catalog: CatalogService,
    session: Session,
    keitaro_id: int,
    *,
    force: bool = False,
) -> editor.CampaignDetail:
    """Первый выбор кампании создаёт локальную копию через Fetch.

    Если локальная кампания уже есть, открываем её обычным Fetch (с проверкой
    LOCAL_CHANGES/BUSY). Иначе сначала убеждаемся, что кампания существует в
    Keitaro, создаём минимальную строку Campaign, а затем переиспользуем
    fetch_campaign — он заполнит потоки и офферы в одной транзакции.
    """
    existing = session.scalar(
        select(models.Campaign).where(models.Campaign.keitaro_id == keitaro_id)
    )
    if existing is not None:
        return fetch_campaign(client, catalog, session, existing.id, force=force)

    try:
        remote = client.request("GET", f"campaigns/{keitaro_id}")
    except AppError as e:
        if e.code == "KEITARO_NOT_FOUND":
            raise AppError(
                "NOT_FOUND", f"Кампания Keitaro {keitaro_id} не найдена", 404
            ) from e
        raise
    if not isinstance(remote, dict) or remote.get("id") is None:
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro не вернул кампанию для Fetch", 502)

    settings = get_settings()

    def pick_int(value, default: int | None) -> int | None:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    group_id = pick_int(remote.get("group_id"), settings.keitaro_default_group_id)
    source_id = pick_int(remote.get("traffic_source_id"), settings.keitaro_default_traffic_source_id)
    if group_id is None or source_id is None:
        raise AppError(
            "KEITARO_BAD_RESPONSE",
            "В ответе Keitaro нет group_id/traffic_source_id и значения по умолчанию не заданы",
            502,
        )

    campaign = models.Campaign(
        keitaro_id=keitaro_id,
        name=str(remote.get("name") or f"Campaign #{keitaro_id}"),
        alias=str(remote.get("alias") or str(keitaro_id)),
        domain_id=pick_int(remote.get("domain_id"), settings.keitaro_default_domain_id),
        group_id=group_id,
        source_id=source_id,
    )
    session.add(campaign)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(models.Campaign).where(models.Campaign.keitaro_id == keitaro_id)
        )
        if existing is not None:
            return fetch_campaign(client, catalog, session, existing.id, force=force)
        raise

    return fetch_campaign(client, catalog, session, campaign.id, force=True)
