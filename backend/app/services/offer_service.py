"""Локальные мутации офферов потока."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db import models
from app.schemas.editor import CampaignDetail
from app.services import editor_service
from app.services.catalog_service import CatalogService
from app.services.keitaro_client import KeitaroClient
from app.services.share_calculator import OfferInput, calculate_shares


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _flow_or_404(session: Session, campaign_id: int, flow_id: int) -> models.CampaignFlow:
    flow = session.scalar(
        select(models.CampaignFlow).where(
            models.CampaignFlow.id == flow_id,
            models.CampaignFlow.campaign_id == campaign_id,
        )
    )
    if flow is None:
        raise AppError("NOT_FOUND", f"Поток {flow_id} не найден в кампании {campaign_id}", 404)
    return flow


def _lock_flow(session: Session, campaign_id: int, flow_id: int) -> models.CampaignFlow:
    flow = session.scalar(
        select(models.CampaignFlow)
        .where(
            models.CampaignFlow.id == flow_id,
            models.CampaignFlow.campaign_id == campaign_id,
        )
        .with_for_update()
    )
    if flow is None:
        raise AppError("NOT_FOUND", f"Поток {flow_id} не найден в кампании {campaign_id}", 404)
    return flow


def _offers(session: Session, flow_id: int) -> list[models.CampaignOffer]:
    return list(session.scalars(
        select(models.CampaignOffer)
        .where(models.CampaignOffer.flow_id == flow_id)
        .order_by(models.CampaignOffer.created_at, models.CampaignOffer.id)
    ).all())


def _finish(
    session: Session,
    flow: models.CampaignFlow,
    campaign_id: int,
    *,
    new_ids: set[int] | None = None,
    pivot_ids: set[int] | None = None,
    reset_free: bool = False,
) -> CampaignDetail:
    """Пересчитать shares, сдвинуть revision/статус, закоммитить и вернуть карточку."""
    new_ids, pivot_ids = new_ids or set(), pivot_ids or set()
    try:
        active = [o for o in _offers(session, flow.id) if o.is_active]
        if reset_free:
            # После удаления или снятия Fixed старые веса больше не отражают
            # намерение пользователя: свободные доли делятся заново поровну.
            for offer in active:
                if not offer.is_fixed:
                    offer.share = 0
        shares = calculate_shares([
            OfferInput(
                id=o.id,
                share=o.share,
                is_fixed=bool(o.is_fixed),
                is_new=o.id in new_ids,
                is_pivot=o.id in pivot_ids,
            )
            for o in active
        ])
        by_id = {s.id: s.share for s in shares}
        for offer in active:
            offer.share = by_id[offer.id]
        flow.revision = (flow.revision or 0) + 1
        if flow.sync_status != "uploading":
            flow.sync_status = "modified"
        session.commit()
    except Exception:
        session.rollback()
        raise
    return editor_service.get_campaign(session, campaign_id)


def _active_offer(session: Session, flow_id: int, offer_id: int) -> models.CampaignOffer:
    row = session.scalar(
        select(models.CampaignOffer).where(
            models.CampaignOffer.flow_id == flow_id,
            models.CampaignOffer.keitaro_offer_id == offer_id,
            models.CampaignOffer.is_active.is_(True),
        )
    )
    if row is None:
        raise AppError(
            "NOT_FOUND", f"Активный оффер {offer_id} не найден в потоке {flow_id}", 404
        )
    return row


def add_offer(
    client: KeitaroClient,
    catalog: CatalogService,
    session: Session,
    campaign_id: int,
    flow_id: int,
    offer_id: int,
) -> CampaignDetail:
    """Добавить оффер или восстановить его из Deleted Offers.

    Произвольный ID принимается даже если оффера нет в каталоге Keitaro: это
    нужно для локальной проверки Fixed/shares. Название в таком случае берётся
    из ID и помечается как недоступное.
    """
    _flow_or_404(session, campaign_id, flow_id)

    found = catalog.get_offer(offer_id)  # сетевой вызов до захвата блокировки
    name = found.name if found is not None else str(offer_id)

    try:
        flow = _lock_flow(session, campaign_id, flow_id)
        row = session.scalar(
            select(models.CampaignOffer).where(
                models.CampaignOffer.flow_id == flow.id,
                models.CampaignOffer.keitaro_offer_id == offer_id,
            )
        )
        if row is not None and row.is_active:
            raise AppError(
                "DUPLICATE_OFFER", f"Оффер {offer_id} уже есть в потоке", 409,
                details={"flow_id": flow.id, "offer_id": offer_id},
            )
        if row is None:
            row = models.CampaignOffer(
                flow_id=flow.id,
                keitaro_offer_id=offer_id,
                offer_name=name,
                share=0,
                is_fixed=False,
                is_active=True,
            )
            session.add(row)
        else:
            # Добавление из архива = restore: прежний share не используется.
            row.is_active = True
            row.deleted_at = None
            row.is_fixed = False
            row.share = 0
            row.offer_name = name
        session.flush()
        return _finish(session, flow, campaign_id, new_ids={row.id})
    except Exception:
        session.rollback()
        raise


def delete_offer(
    session: Session,
    campaign_id: int,
    flow_id: int,
    offer_id: int,
) -> CampaignDetail:
    """Мягкое удаление; последний share сохраняется в архивной строке."""
    try:
        flow = _lock_flow(session, campaign_id, flow_id)
        row = _active_offer(session, flow.id, offer_id)
        row.is_active = False
        row.deleted_at = _now()
        return _finish(session, flow, campaign_id, reset_free=True)
    except Exception:
        session.rollback()
        raise


def restore_offer(
    session: Session,
    campaign_id: int,
    flow_id: int,
    offer_id: int,
) -> CampaignDetail:
    """Restore — новый оффер со средним весом, Fixed снят."""
    try:
        flow = _lock_flow(session, campaign_id, flow_id)
        row = session.scalar(
            select(models.CampaignOffer).where(
                models.CampaignOffer.flow_id == flow.id,
                models.CampaignOffer.keitaro_offer_id == offer_id,
                models.CampaignOffer.is_active.is_(False),
            )
        )
        if row is None:
            raise AppError(
                "NOT_FOUND", f"Оффер {offer_id} не найден в Deleted Offers потока {flow_id}", 404
            )
        row.is_active = True
        row.deleted_at = None
        row.is_fixed = False
        row.share = 0  # прежний share в расчёте не участвует
        session.flush()
        return _finish(session, flow, campaign_id, new_ids={row.id})
    except Exception:
        session.rollback()
        raise


def patch_offer(
    session: Session,
    campaign_id: int,
    flow_id: int,
    offer_id: int,
    *,
    share: int | None = None,
    is_fixed: bool | None = None,
) -> CampaignDetail:
    """Ручной ввод share делает оффер закреплённым."""
    if share is None and is_fixed is None:
        raise AppError("INVALID_REQUEST", "Пустой PATCH", 422)
    if share is not None and is_fixed is False:
        raise AppError(
            "INVALID_REQUEST", "Чтобы ввести share, сначала снимите Fixed отдельным запросом", 422
        )
    try:
        flow = _lock_flow(session, campaign_id, flow_id)
        row = _active_offer(session, flow.id, offer_id)
        pivot_ids: set[int] = set()
        reset_free = False
        if share is not None:
            row.share = share
            row.is_fixed = True
            pivot_ids.add(row.id)
        else:
            was_fixed = bool(row.is_fixed)
            row.is_fixed = bool(is_fixed)
            reset_free = was_fixed and not row.is_fixed
        return _finish(session, flow, campaign_id, pivot_ids=pivot_ids, reset_free=reset_free)
    except Exception:
        session.rollback()
        raise
