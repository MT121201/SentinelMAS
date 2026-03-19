"""Create rag_kb_entries table

Revision ID: 005
Revises: 004
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rag_kb_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("error_pattern", sa.Text, nullable=False),        # sanitised error description
        sa.Column("fix_steps", sa.Text, nullable=False),             # sanitised fix instructions
        sa.Column("tags", ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("embedding_id", sa.String(128), nullable=True),    # Qdrant point ID
        sa.Column("bm25_doc_id", sa.Integer, nullable=True),         # position in BM25 index
        sa.Column("source", sa.String(64), nullable=False, server_default="agent_resolution"),
        # source: agent_resolution | manual | import
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_kb_tags", "rag_kb_entries", ["tags"], postgresql_using="gin")
    op.create_index("idx_kb_source", "rag_kb_entries", ["source"])


def downgrade() -> None:
    op.drop_index("idx_kb_source")
    op.drop_index("idx_kb_tags")
    op.drop_table("rag_kb_entries")
