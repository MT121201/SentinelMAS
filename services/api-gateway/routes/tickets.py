"""
Ticket endpoints:
  POST /tickets           submit ticket → 202 Accepted
  GET  /tickets/{id}      poll status
  GET  /tickets/{id}/log  sanitised agent log
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shared.db import get_db
from shared.task_queue import enqueue

from auth import get_current_user
from limiter import limiter
from models import TicketCreate, TicketLogEntry, TicketResponse
from sanitiser import sanitise_log, sanitise_ticket_input

router = APIRouter(tags=["tickets"])

# Import Ticket ORM model inline to avoid circular dep with shared.db
from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from shared.db import Base


class _Ticket(Base):
    """Lightweight ORM ref — canonical model lives in alembic migrations."""
    __tablename__ = "tickets"
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id = Column(String(64))
    description = Column(Text)
    severity = Column(String(16))
    status = Column(String(32), default="queued")
    agent_id = Column(String(64))
    trace_id = Column(String(64))
    resolution_summary = Column(Text)
    created_at = Column(__import__("sqlalchemy").TIMESTAMP(timezone=True),
                        server_default=__import__("sqlalchemy").func.now())
    updated_at = Column(__import__("sqlalchemy").TIMESTAMP(timezone=True),
                        server_default=__import__("sqlalchemy").func.now())


@router.post("/tickets", status_code=202, response_model=TicketResponse)
@limiter.limit("20/minute")
async def submit_ticket(
    request: Request,
    body: TicketCreate,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """
    Validate, sanitise, persist, and enqueue a support ticket.
    Returns 202 immediately — processing is async.
    """
    clean_description = sanitise_ticket_input(body.description)

    ticket_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    ticket = _Ticket(
        id=ticket_id,
        server_id=body.server_id,
        description=clean_description,
        status="queued",
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    await db.flush()  # get DB row before enqueue

    task = {
        "task_id": str(ticket_id),
        "task_type": "ticket",
        "ticket_id": str(ticket_id),
        "server_id": body.server_id,
        "description": clean_description,
        "created_at": now.isoformat(),
    }
    await enqueue("client", task)

    return TicketResponse(
        ticket_id=ticket_id,
        server_id=body.server_id,
        status="queued",
        created_at=now,
        updated_at=now,
        poll_url=f"/tickets/{ticket_id}",
    )


@router.get("/tickets/{ticket_id}", response_model=TicketResponse)
@limiter.limit("60/minute")
async def get_ticket(
    request: Request,
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Poll ticket status. Resolution summary is sanitised before return."""
    ticket = await db.scalar(select(_Ticket).where(_Ticket.id == ticket_id))
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    summary = sanitise_log(ticket.resolution_summary) if ticket.resolution_summary else None

    return TicketResponse(
        ticket_id=ticket.id,
        server_id=ticket.server_id,
        status=ticket.status,
        severity=ticket.severity,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        assigned_agent=ticket.agent_id,
        resolution_summary=summary,
        trace_id=ticket.trace_id,
    )


@router.get("/tickets/{ticket_id}/log", response_model=list[TicketLogEntry])
@limiter.limit("30/minute")
async def get_ticket_log(
    request: Request,
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """
    Return sanitised agent log for a ticket.
    Full structured logs live in Loki (Phase 8). For now returns
    a synthesised entry from the ticket's current state.
    """
    ticket = await db.scalar(select(_Ticket).where(_Ticket.id == ticket_id))
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    entries = []
    if ticket.resolution_summary:
        entries.append(TicketLogEntry(
            timestamp=ticket.updated_at,
            agent_id=ticket.agent_id or "unknown",
            step="resolution",
            detail=sanitise_log(ticket.resolution_summary),
        ))
    return entries
