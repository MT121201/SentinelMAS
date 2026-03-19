"""Create tickets table

Revision ID: 003
Revises: 002
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("severity", sa.String(16), nullable=True),         # LOW|MEDIUM|HIGH|CRITICAL
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        # queued → assigned → thinking → executing → verifying → done | failed | escalated
        sa.Column("agent_id", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("resolution_summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("idx_tickets_status", "tickets", ["status", "created_at"])
    op.create_index("idx_tickets_server", "tickets", ["server_id"])
    op.create_index("idx_tickets_trace", "tickets", ["trace_id"])


def downgrade() -> None:
    op.drop_index("idx_tickets_trace")
    op.drop_index("idx_tickets_server")
    op.drop_index("idx_tickets_status")
    op.drop_table("tickets")
