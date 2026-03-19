"""Create credential_access_log table

Revision ID: 002
Revises: 001
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credential_access_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),   # connect | execute | close
        sa.Column("accessed_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("success", sa.Boolean, nullable=False),
    )
    op.create_index("idx_access_log_server", "credential_access_log", ["server_id", "accessed_at"])
    op.create_index("idx_access_log_trace", "credential_access_log", ["trace_id"])


def downgrade() -> None:
    op.drop_index("idx_access_log_trace")
    op.drop_index("idx_access_log_server")
    op.drop_table("credential_access_log")
