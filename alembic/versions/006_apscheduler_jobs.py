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
    # Use execute for IF NOT EXISTS since op.create_table has no equivalent
    op.execute("""
        CREATE TABLE IF NOT EXISTS apscheduler_jobs (
            id VARCHAR(191) NOT NULL PRIMARY KEY,
            next_run_time DOUBLE PRECISION,
            job_state BYTEA NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_apscheduler_jobs_next_run_time
        ON apscheduler_jobs (next_run_time)
    """)


def downgrade() -> None:
    op.drop_index("ix_apscheduler_jobs_next_run_time")
    op.drop_table("apscheduler_jobs")
