# API DESIGN — GPU-MAS FastAPI

## 1. Route Overview

```
Public (JWT required)
  POST   /auth/token                    ← get JWT (username+password)
  POST   /tickets                       ← submit user ticket
  GET    /tickets/{ticket_id}           ← poll ticket status + result
  GET    /tickets/{ticket_id}/log       ← agent thought chain log

Manager (API Key required)
  GET    /reports/daily                 ← latest daily report
  GET    /reports/daily/{date}          ← specific date report
  GET    /reports/weekly                ← latest weekly report
  GET    /ops/agents                    ← live agent state overview
  GET    /ops/queue                     ← task queue depth + stats
  GET    /ops/cost                      ← token spend summary
  POST   /ops/cost/reset                ← reset daily cost counter (after review)
  GET    /ops/servers                   ← fleet health summary

Admin (API Key + INTERNAL_ADMIN_KEY required)
  GET    /admin/servers                 ← list all registered servers
  POST   /admin/servers                 ← register new server
  PUT    /admin/servers/{id}/credential ← update SSH credentials
  DELETE /admin/servers/{id}            ← decommission server
  POST   /admin/maintenance/trigger     ← manual trigger maintenance run

Internal (INTERNAL_API_KEY, not exposed externally)
  POST   /internal/tasks                ← orchestrator submits tasks
  PUT    /internal/tasks/{id}/status    ← agent updates task status
  POST   /internal/logs                 ← agents write structured logs

System
  GET    /health                        ← liveness + dependency check
  GET    /metrics                       ← Prometheus format
  GET    /docs                          ← OpenAPI (disable in prod)
```

---

## 2. Data Models (Pydantic)

```python
# services/api-gateway/models.py
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID

# --- Auth ---
class TokenRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 86400  # seconds

# --- Tickets ---
class TicketCreate(BaseModel):
    server_id: str = Field(..., description="Target server logical ID")
    description: str = Field(..., min_length=10, max_length=4000)
    attachments: Optional[list[str]] = Field(
        None, description="Base64 encoded log snippets (max 3, each <50KB)"
    )

class TicketResponse(BaseModel):
    ticket_id: UUID
    status: Literal["queued","assigned","thinking","executing","verifying","done","failed","escalated"]
    created_at: datetime
    updated_at: datetime
    assigned_agent: Optional[str] = None
    resolution_summary: Optional[str] = None
    trace_id: Optional[str] = None

class TicketLogEntry(BaseModel):
    timestamp: datetime
    agent_id: str
    step: str
    detail: str  # sanitised

# --- Server Registration ---
class ServerCreate(BaseModel):
    server_id: str = Field(..., pattern=r'^[a-z0-9-_]+$')
    display_name: str
    hostname: str
    port: int = 22
    username: str
    ssh_private_key: str   # PEM format — encrypted immediately, never stored raw
    sudo_password: Optional[str] = None

class ServerInfo(BaseModel):
    server_id: str
    display_name: str
    hostname: str
    port: int
    is_active: bool
    last_health_check: Optional[datetime]
    health_status: Optional[Literal["healthy","degraded","unreachable","unknown"]]

# --- Ops ---
class AgentState(BaseModel):
    agent_id: str
    agent_type: str
    current_task_id: Optional[str]
    status: str
    active_since: Optional[datetime]
    tasks_completed_today: int

class QueueStats(BaseModel):
    pending: int
    in_progress: int
    completed_today: int
    failed_today: int
    escalated_today: int
    avg_resolution_minutes: float

class CostSummary(BaseModel):
    date: str
    total_tokens: int
    estimated_cost_usd: float
    limit_usd: float
    utilisation_pct: float
    llm_calls: int
```

---

## 3. Rate Limiting Strategy

```python
# services/api-gateway/rate_limit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Applied per endpoint:
# POST /tickets        → 20/minute per IP (prevents ticket spam)
# GET  /tickets/{id}   → 60/minute per IP (polling)
# POST /auth/token     → 5/minute per IP (brute force protection)
# GET  /reports/*      → 30/minute per API key
# POST /admin/*        → 10/minute per API key
```

---

## 4. Async Task Response Pattern

```
Client: POST /tickets
  Body: {server_id, description}

Gateway: validates → enqueues → returns immediately

Response 202:
{
  "ticket_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "poll_url": "/tickets/550e8400.../",
  "created_at": "2024-01-15T10:30:00Z"
}

Client: GET /tickets/550e8400.../ (poll every 5s)

Response during processing:
{
  "ticket_id": "...",
  "status": "executing",
  "assigned_agent": "client-agent-02",
  "created_at": "...",
  "updated_at": "2024-01-15T10:30:45Z"
}

Response when done:
{
  "ticket_id": "...",
  "status": "done",
  "resolution_summary": "Docker was not installed on the server. Installed docker-ce v25.0.3 via apt. Verified daemon is running. Issue resolved.",
  "trace_id": "trace_abc123",
  "created_at": "...",
  "updated_at": "2024-01-15T10:33:10Z"
}
```

---

## 5. Error Response Format

```json
{
  "error": {
    "code": "TICKET_SERVER_NOT_FOUND",
    "message": "Server ID 'gpu-node-99' is not registered in the system.",
    "request_id": "req_xyz789"
  }
}
```

Standard HTTP status codes:
- `400` — validation error (Pydantic)
- `401` — missing / invalid JWT
- `403` — valid auth but insufficient permission
- `404` — resource not found
- `422` — unprocessable entity
- `429` — rate limit exceeded
- `500` — internal agent error (includes request_id for log lookup)
- `503` — system in cost-limit shutdown mode

---

## 6. OpenAPI Tags & Grouping

```python
app = FastAPI(
    title="GPU-MAS API",
    version="0.1.0",
    description="Multi-Agent GPU Server Management System",
    docs_url="/docs" if settings.ENV == "development" else None,
    redoc_url=None,
)

# Tag groups shown in Swagger UI
tags_metadata = [
    {"name": "auth",       "description": "Authentication"},
    {"name": "tickets",    "description": "User ticket submission and polling"},
    {"name": "reports",    "description": "Manager reports (API key required)"},
    {"name": "ops",        "description": "Live operational view (API key required)"},
    {"name": "admin",      "description": "Server fleet management (admin key required)"},
    {"name": "system",     "description": "Health and metrics"},
]
```
