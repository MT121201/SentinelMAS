"""Create server_credentials table

Revision ID: 001
Revises:
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "server_credentials",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("server_id", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("hostname", sa.Text, nullable=False),          # plaintext — not a secret
        sa.Column("port", sa.Integer, nullable=False, server_default="22"),
        sa.Column("username_enc", sa.LargeBinary, nullable=False),   # AES-256-GCM ciphertext
        sa.Column("ssh_key_enc", sa.LargeBinary, nullable=False),    # AES-256-GCM ciphertext
        sa.Column("sudo_pass_enc", sa.LargeBinary, nullable=True),   # optional
        sa.Column("key_nonce", sa.LargeBinary, nullable=False),      # GCM nonce for ssh_key
        sa.Column("user_nonce", sa.LargeBinary, nullable=False),     # GCM nonce for username
        sa.Column("sudo_nonce", sa.LargeBinary, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("rotated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("server_credentials")
