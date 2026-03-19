"""Create daily_health_snapshots table

Revision ID: 004
Revises: 003
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_health_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", sa.String(64), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("metrics_json", JSONB, nullable=False),
        # e.g. {"gpu_util": 85, "disk_used_pct": 72, "mem_used_pct": 60,
        #        "services_ok": ["docker","ssh"], "services_down": [],
        #        "blacklisted": false, "issues": []}
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),  # ok | warn | critical
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("server_id", "date", name="uq_snapshot_server_date"),
    )
    op.create_index("idx_snapshots_server_date", "daily_health_snapshots", ["server_id", "date"])


def downgrade() -> None:
    op.drop_index("idx_snapshots_server_date")
    op.drop_table("daily_health_snapshots")
