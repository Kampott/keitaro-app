"""Локальные модели редактора (ТЗ §5)."""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String,
    Text, UniqueConstraint, false, func, true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (UniqueConstraint("keitaro_id", name="uq_campaign_keitaro_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    flows: Mapped[list["CampaignFlow"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    logs: Mapped[list["SyncLog"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class CampaignFlow(Base):
    __tablename__ = "campaign_flows"
    __table_args__ = (
        UniqueConstraint("keitaro_flow_id", name="uq_flow_keitaro_id"),
        Index("ix_flow_campaign", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    keitaro_flow_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="regular")
    schema: Mapped[str] = mapped_column(String(32), nullable=False, default="landings")
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    sync_status: Mapped[str] = mapped_column(String(16), nullable=False, default="synced")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    remote_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Полезная часть ответа GET /streams/{id} по схеме StreamRequestPut:
    # нужна, если частичный PUT с offers затирает остальные поля потока (§2.3 п.6, §4.9).
    remote_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    campaign: Mapped["Campaign"] = relationship(back_populates="flows")
    offers: Mapped[list["CampaignOffer"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", order_by="CampaignOffer.id"
    )
    logs: Mapped[list["SyncLog"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan"
    )


class CampaignOffer(Base):
    __tablename__ = "campaign_offers"
    __table_args__ = (
        UniqueConstraint("flow_id", "keitaro_offer_id", name="uq_offer_flow_keitaro"),
        CheckConstraint("share >= 0 AND share <= 100", name="ck_offer_share"),
        CheckConstraint(
            "(is_active AND deleted_at IS NULL) OR (NOT is_active AND deleted_at IS NOT NULL)",
            name="ck_offer_active_deleted",
        ),
        Index("ix_campaign_offer_flow_active", "flow_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flow_id: Mapped[int] = mapped_column(
        ForeignKey("campaign_flows.id", ondelete="CASCADE"), nullable=False
    )
    keitaro_offer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    offer_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    share: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    keitaro_state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    flow: Mapped["CampaignFlow"] = relationship(back_populates="offers")


class SyncLog(Base):
    __tablename__ = "sync_logs"
    __table_args__ = (
        Index("ix_sync_log_campaign", "campaign_id"),
        Index("ix_sync_log_flow", "flow_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    flow_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaign_flows.id", ondelete="CASCADE"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    campaign: Mapped["Campaign"] = relationship(back_populates="logs")
    flow: Mapped["CampaignFlow | None"] = relationship(back_populates="logs")