"""
SQLAlchemy ORM models for the vault service.
These mirror the Alembic migrations exactly.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.db import Base


class ServerCredential(Base):
    __tablename__ = "server_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    hostname: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int] = mapped_column(default=22)
    username_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ssh_key_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sudo_pass_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    key_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    user_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sudo_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    rotated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CredentialAccessLog(Base):
    __tablename__ = "credential_access_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)  # connect|execute|close
    accessed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
