"""remote_payload у потока: исходный StreamRequestPut для fallback при Upload.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaign_flows",
        sa.Column("remote_payload", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("campaign_flows", "remote_payload")
