"""campaigns, campaign_flows, campaign_offers, sync_logs

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("keitaro_id", name="uq_campaign_keitaro_id"),
    )

    op.create_table(
        "campaign_flows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keitaro_flow_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("type", sa.String(32), nullable=False, server_default="regular"),
        sa.Column("schema", sa.String(32), nullable=False, server_default="landings"),
        sa.Column("state", sa.String(32), nullable=False, server_default="active"),
        sa.Column("sync_status", sa.String(16), nullable=False, server_default="synced"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remote_hash", sa.String(64), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("last_uploaded_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("keitaro_flow_id", name="uq_flow_keitaro_id"),
    )
    op.create_index("ix_flow_campaign", "campaign_flows", ["campaign_id"])

    op.create_table(
        "campaign_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("campaign_flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keitaro_offer_id", sa.Integer(), nullable=False),
        sa.Column("offer_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("share", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("keitaro_state", sa.String(32), nullable=False, server_default="active"),
        sa.Column("is_fixed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("flow_id", "keitaro_offer_id", name="uq_offer_flow_keitaro"),
        sa.CheckConstraint("share >= 0 AND share <= 100", name="ck_offer_share"),
        sa.CheckConstraint(
            "(is_active AND deleted_at IS NULL) OR (NOT is_active AND deleted_at IS NOT NULL)",
            name="ck_offer_active_deleted",
        ),
    )
    op.create_index("ix_campaign_offer_flow_active", "campaign_offers", ["flow_id", "is_active"])

    op.create_table(
        "sync_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_id", sa.Integer(), sa.ForeignKey("campaign_flows.id", ondelete="CASCADE"), nullable=True),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sync_log_campaign", "sync_logs", ["campaign_id"])
    op.create_index("ix_sync_log_flow", "sync_logs", ["flow_id"])


def downgrade() -> None:
    op.drop_table("sync_logs")
    op.drop_table("campaign_offers")
    op.drop_table("campaign_flows")
    op.drop_table("campaigns")