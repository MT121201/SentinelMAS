"""Create apscheduler_jobs table (APScheduler SQLAlchemy job store)

Revision ID: 006
Revises: 005
Create Date: 2026-03-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schema expected by APScheduler's SQLAlchemyJobStore
    op.create_table(
        "apscheduler_jobs",
        sa.Column("id", sa.String(191), primary_key=True),
        sa.Column("next_run_time", sa.Float(precision=53), nullable=True),
        sa.Column("job_state", sa.LargeBinary, nullable=False),
    )
    op.create_index(
        "ix_apscheduler_jobs_next_run_time",
        "apscheduler_jobs",
        ["next_run_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_apscheduler_jobs_next_run_time")
    op.drop_table("apscheduler_jobs")
