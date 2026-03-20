"""Pydantic request/response models for the API Gateway."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Auth ──────────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # seconds


# ── Tickets ───────────────────────────────────────────────────────────────────

TicketStatus = Literal[
    "queued", "assigned", "thinking", "executing", "verifying",
    "done", "failed", "escalated"
]


class TicketCreate(BaseModel):
    server_id: str = Field(..., description="Target server logical ID")
    description: str = Field(..., min_length=10, max_length=4000)
    attachments: Optional[list[str]] = Field(
        None, description="Base64-encoded log snippets (max 3, each <50 KB)"
    )


class TicketResponse(BaseModel):
    ticket_id: UUID
    server_id: str
    status: TicketStatus
    severity: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    assigned_agent: Optional[str] = None
    resolution_summary: Optional[str] = None
    trace_id: Optional[str] = None
    poll_url: Optional[str] = None


class TicketLogEntry(BaseModel):
    timestamp: datetime
    agent_id: str
    step: str
    detail: str  # sanitised


# ── Servers ───────────────────────────────────────────────────────────────────

class ServerCreate(BaseModel):
    server_id: str = Field(..., pattern=r"^[a-z0-9\-_]+$", max_length=64)
    display_name: str = Field(..., max_length=128)
    hostname: str
    port: int = 22
    username: str
    ssh_private_key: str   # PEM — forwarded to vault, never stored here
    sudo_password: Optional[str] = None


class ServerInfo(BaseModel):
    server_id: str
    display_name: str
    hostname: str
    port: int
    is_active: bool
    last_snapshot_date: Optional[str] = None
    health_status: Optional[Literal["healthy", "degraded", "unreachable", "unknown"]] = None


# ── Ops ───────────────────────────────────────────────────────────────────────

class AgentStateInfo(BaseModel):
    agent_id: str
    agent_type: str
    current_task_id: Optional[str] = None
    status: str
    active_since: Optional[datetime] = None
    tasks_completed_today: int = 0


class QueueStats(BaseModel):
    queue_name: str
    pending: int
    completed_today: int
    failed_today: int
    escalated_today: int


class CostSummary(BaseModel):
    date: str
    total_cost_usd: float
    limit_usd: float
    utilisation_pct: float
    rpm_used: int
    rpm_limit: int
    tpm_used: int
    tpm_limit: int


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
