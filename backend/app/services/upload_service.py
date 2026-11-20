"""Upload потока в Keitaro (ТЗ §4.9)."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models
from app.services import editor_service, sync_service
from app.services.keitaro_client import KeitaroClient
from app.services.offer_service import _assert_editable
from app.services.share_calculator import shares_valid


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _flow_or_404(session: Session, flow_id: int) -> models.CampaignFlow:
    flow = session.get(models.CampaignFlow, flow_id)
    if flow is None:
        raise AppError("NOT_FOUND", f"Поток {flow_id} не найден", 404)
    return flow


def _active_offers(session: Session, flow_id: int) -> list[models.CampaignOffer]:
    return list(session.scalars(
        select(models.CampaignOffer)
        .where(
            models.CampaignOffer.flow_id == flow_id,
            models.CampaignOffer.is_active.is_(True),
        )
        .order_by(models.CampaignOffer.created_at, models.CampaignOffer.id)
    ).all())


def _offer_snapshot(rows: list[models.CampaignOffer]) -> list[dict]:
    """Неизменяемый снимок: только активные офферы и три поля запроса Keitaro."""
    return [
        {"offer_id": r.keitaro_offer_id, "share": r.share, "state": r.keitaro_state}
        for r in rows
    ]


def _remote_offers_match(stream: dict, snapshot: list[dict]) -> bool:
    remote: dict[int, tuple[int, str]] = {}
    for row in stream.get("offers") or []:
        if not isinstance(row, dict) or row.get("offer_id") is None:
            continue
        try:
            remote[int(row["offer_id"])] = (
                int(row.get("share") or 0), str(row.get("state") or "active")
            )
        except (TypeError, ValueError):
            return False
    expected = {o["offer_id"]: (o["share"], o["state"]) for o in snapshot}
    return remote == expected


def recover_stale_uploads(session: Session) -> int:
    """§4.9 п.6: зависшие uploading после перезапуска переводятся в error."""
    flows = session.scalars(
        select(models.CampaignFlow).where(models.CampaignFlow.sync_status == "uploading")
    ).all()
    for flow in flows:
        flow.sync_status = "error"
        session.add(models.SyncLog(
            campaign_id=flow.campaign_id,
            flow_id=flow.id,
            operation="upload",
            status="error",
            message="Зависший Upload при старте приложения",
        ))
    session.commit()
    return len(flows)


def _mark_error(session: Session, campaign_id: int, flow_id: int, error: Exception) -> None:
    """Локальные данные не трогаем, кроме статуса и error-лога (§4.9 п.6)."""
    message = error.message if isinstance(error, AppError) else str(error)
    try:
        failed = session.scalar(
            select(models.CampaignFlow).where(models.CampaignFlow.id == flow_id).with_for_update()
        )
        if failed is not None and failed.sync_status == "uploading":
            failed.sync_status = "error"
        session.add(models.SyncLog(
            campaign_id=campaign_id,
            flow_id=flow_id,
            operation="upload",
            status="error",
            message=(message or "Upload не удался")[:2000],
        ))
        session.commit()  # get_db не коммитит за endpoint
    except Exception:
        session.rollback()


def upload_flow(
    client: KeitaroClient,
    session: Session,
    flow_id: int,
    *,
    force: bool = False,
):
    """§4.9: отправить снимок активных офферов и подтвердить результат чтением."""
    flow = _flow_or_404(session, flow_id)
    campaign_id = flow.campaign_id
    keitaro_flow_id = flow.keitaro_flow_id
    campaign = session.get(models.Campaign, campaign_id)
    _assert_editable(session, flow)  # FLOW_READONLY: Upload read-only потока запрещён

    # 1. Сетевые проверки до захвата локальных блокировок.
    try:
        remote_campaign = client.request("GET", f"campaigns/{campaign.keitaro_id}")
    except AppError as e:
        if e.code == "KEITARO_NOT_FOUND":
            raise AppError(
                "CAMPAIGN_ARCHIVED", "Кампания не найдена или архивирована в Keitaro", 409
            ) from e
        raise
    if not isinstance(remote_campaign, dict):
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro не вернул кампанию при Upload", 502)
    state = str(remote_campaign.get("state") or "active")
    if state != "active":
        raise AppError(
            "CAMPAIGN_ARCHIVED", f"Кампания в Keitaro имеет состояние {state}", 409
        )

    remote_stream = client.request("GET", f"streams/{keitaro_flow_id}")
    if not isinstance(remote_stream, dict):
        raise AppError("KEITARO_BAD_RESPONSE", "Keitaro не вернул поток при Upload", 502)
    if not force and sync_service.flow_remote_hash(remote_stream) != flow.remote_hash:
        raise AppError(
            "REMOTE_CHANGED",
            "Поток изменился в Keitaro: сделайте Fetch или повторите Upload с force=true",
            409,
            details={"flow_id": flow_id},
        )

    # 2. Блокировка, валидация, r0 и перевод в uploading — одна транзакция.
    try:
        locked = session.scalar(
            select(models.CampaignFlow).where(models.CampaignFlow.id == flow_id).with_for_update()
        )
        if locked.sync_status == "uploading":
            raise AppError("BUSY", "Поток уже отправляется", 409, details={"flow_id": flow_id})
        _assert_editable(session, locked)
        rows = _active_offers(session, flow_id)
        if not rows:
            raise AppError("EMPTY_FLOW", "В потоке нет активных офферов", 422)
        if not shares_valid([r.share for r in rows]):
            raise AppError("INVALID_SHARES", "Некорректные shares активных офферов", 422)
        snapshot = _offer_snapshot(rows)
        r0 = locked.revision
        locked.sync_status = "uploading"
        session.commit()
    except Exception:
        session.rollback()
        raise

    # 3–5. PUT, при необходимости полный PUT, контрольное чтение и финализация.
    try:
        client.request("PUT", f"streams/{keitaro_flow_id}", json={"offers": snapshot})

        verified = client.request("GET", f"streams/{keitaro_flow_id}")
        if not isinstance(verified, dict):
            raise AppError("KEITARO_BAD_RESPONSE", "Некорректный ответ контрольного чтения", 502)

        # Частичный PUT может затереть фильтры/лендинги/action_* (проверка WRITE не
        # проводилась). Если это случилось — повторяем полным StreamRequestPut.
        if sync_service.hash_without_offers(verified) != sync_service.hash_without_offers(remote_stream):
            # Основа — сохранённый при Fetch/Upload StreamRequestPut, сверху — свежие
            # значения из GET; так не теряются поля, которых нет в ответе текущего чтения.
            full = dict(flow.remote_payload or {})
            full.update(sync_service.stream_request_payload(remote_stream))
            full["offers"] = snapshot
            client.request("PUT", f"streams/{keitaro_flow_id}", json=full)
            verified = client.request("GET", f"streams/{keitaro_flow_id}")
            if not isinstance(verified, dict):
                raise AppError("KEITARO_BAD_RESPONSE", "Некорректный ответ после полного PUT", 502)

        if not _remote_offers_match(verified, snapshot):
            raise AppError(
                "KEITARO_BAD_RESPONSE",
                "Контрольное чтение не подтвердило offers после Upload",
                502,
                details={"flow_id": flow_id},
            )

        final = session.scalar(
            select(models.CampaignFlow).where(models.CampaignFlow.id == flow_id).with_for_update()
        )
        final.remote_hash = sync_service.flow_remote_hash(verified)
        final.remote_payload = sync_service.stream_request_payload(verified)
        final.last_uploaded_at = _now()
        # Правки во время uploading не считаются отправленными (§4.9 п.5, п.7).
        final.sync_status = "synced" if final.revision == r0 else "modified"
        session.add(models.SyncLog(
            campaign_id=campaign_id,
            flow_id=flow_id,
            operation="upload",
            status="success",
            message=f"Upload: поток {keitaro_flow_id}, офферов: {len(snapshot)}",
        ))
        session.commit()
    except Exception as e:
        session.rollback()
        _mark_error(session, campaign_id, flow_id, e)
        raise

    return editor_service.get_campaign(session, campaign_id)
